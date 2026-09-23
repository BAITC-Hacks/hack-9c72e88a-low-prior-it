"""Checks the shared API boundaries introduced by consolidating the team branches."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from wind_backend.main import create_app

from tests.conftest import ISSUE, snapshot


@pytest.fixture
def dataset(client):
    rows = []
    for hour in range(-24, 97):
        moment = (ISSUE + timedelta(hours=hour)).isoformat()
        rows.append(
            {
                "turbine_id": "turbine-1",
                "valid_time": moment,
                "available_at": moment,
                "wind_speed_ms": 4 + hour % 12,
                "temperature_c": -5 + hour % 8,
                "power_normalized": 0.1 + (hour % 20) * 0.04,
            }
        )
    response = client.post(
        "/api/v1/datasets",
        json={
            "name": "Artificial integration readings",
            "is_demo": True,
            "provenance": "Synthetic hourly fixture; zero reporting latency",
            "observations": rows,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_observation_window_and_provenance(client, dataset):
    assert client.get("/api/v1/datasets").json()[0]["provenance"] == dataset["provenance"]
    path = f"/api/v1/datasets/{dataset['id']}/observations"
    params = {"start": ISSUE.isoformat(), "end": (ISSUE + timedelta(hours=1)).isoformat()}
    response = client.get(path, params=params)
    assert response.status_code == 200
    assert len(response.json()) == 2
    assert response.json()[0]["valid_time"] == "2026-01-31T00:00:00Z"
    assert (
        client.get(
            path, params=params | {"end": (ISSUE - timedelta(hours=1)).isoformat()}
        ).status_code
        == 422
    )
    assert client.get(path, params=params | {"start": "2026-01-31T00:00:00"}).status_code == 422
    assert client.get("/api/v1/datasets/unknown/observations", params=params).status_code == 404


@pytest.mark.parametrize(
    "algorithm", ["binned-power-curve", "persistence", "weather-ridge", "catboost"]
)
def test_train_restart_and_forecast(client, settings, dataset, algorithm):
    cutoff = ISSUE + timedelta(hours=48)
    weather = snapshot(available_at=ISSUE)
    assert (
        client.post("/api/v1/weather/snapshots", json=weather.model_dump(mode="json")).status_code
        == 201
    )
    request = {
        "dataset_id": dataset["id"],
        "trained_through": cutoff.isoformat(),
        "algorithm": algorithm,
    }
    if algorithm == "catboost":
        request.update(
            first_origin=ISSUE.isoformat(),
            last_origin=ISSUE.isoformat(),
            horizon_hours=48,
            iterations=10,
            depth=2,
        )
    response = client.post("/api/v1/models/train", json=request)
    assert response.status_code == 201, response.text
    model = response.json()
    assert model["training_rows"] > 0
    assert model["is_demo"] is True
    with TestClient(create_app(settings)) as restarted:
        run = restarted.post(
            "/api/v1/forecasts",
            json={
                "turbine_ids": ["turbine-1"],
                "issued_at": cutoff.isoformat(),
                "horizon_hours": 48,
                "weather_source": "demo",
                "model_id": model["id"],
            },
        )
        assert run.status_code == 202, run.text
        result = restarted.get(f"/api/v1/forecasts/{run.json()['id']}").json()
        assert result["status"] == "succeeded", result["error"]
        assert result["result"]["is_demo"] is True
        assert len(result["result"]["points"]) == 48
        assert all(0 <= row["power_normalized"] <= 1 for row in result["result"]["points"])


def test_ridge_rejects_unverified_training_weather(client, dataset):
    weather = snapshot(verification="unverified", available_at=None, availability_evidence="")
    assert (
        client.post("/api/v1/weather/snapshots", json=weather.model_dump(mode="json")).status_code
        == 201
    )
    response = client.post(
        "/api/v1/models/train",
        json={
            "dataset_id": dataset["id"],
            "trained_through": (ISSUE + timedelta(hours=48)).isoformat(),
            "algorithm": "weather-ridge",
        },
    )
    assert response.status_code == 422
    assert "verified forecasts" in response.json()["message"]
