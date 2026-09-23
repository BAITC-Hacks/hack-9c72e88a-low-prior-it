import csv
import io

import pytest
from fastapi.testclient import TestClient
from wind_backend.main import create_app


def test_demo_pipeline_and_csv(client, forecast_request, settings):
    response = client.post("/api/v1/forecasts", json=forecast_request)
    assert response.status_code == 202
    identifier = response.json()["id"]
    run = client.get(f"/api/v1/forecasts/{identifier}").json()
    assert run["status"] == "succeeded"
    assert run["result"]["is_demo"] is True
    assert len(run["result"]["points"]) == 96
    assert {p["lead_hours"] for p in run["result"]["points"]} == set(range(1, 49))
    assert all(0 <= p["power_normalized"] <= 1 for p in run["result"]["points"])
    assert run["events"][-1]["stage"] == "complete"
    exported = client.get(f"/api/v1/forecasts/{identifier}/export")
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert len(rows) == 96
    assert rows[0]["weather_available_at"]
    unchanged = client.post(f"/api/v1/forecasts/{identifier}/refresh").json()
    assert unchanged["changed"] is False
    assert unchanged["run"]["id"] == identifier
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(f"/api/v1/forecasts/{identifier}").json()["result"] == run["result"]


@pytest.mark.parametrize(
    "changes",
    [
        {"issued_at": "2026-01-31T00:00:00"},
        {"issued_at": "2026-01-31T00:30:00Z"},
        {"horizon_hours": 25},
        {"turbine_ids": ["turbine-1", "turbine-1"]},
        {"surprise": "not in contract"},
    ],
)
def test_request_contract_rejects_ambiguous_input(client, forecast_request, changes):
    response = client.post("/api/v1/forecasts", json=forecast_request | changes)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_unknown_resource_and_missing_archive_are_explicit(client, forecast_request):
    assert client.get("/api/v1/forecasts/not-real").status_code == 404
    assert (
        client.post(
            "/api/v1/forecasts", json=forecast_request | {"turbine_ids": ["unknown"]}
        ).status_code
        == 404
    )
    response = client.post(
        "/api/v1/forecasts", json=forecast_request | {"weather_source": "archive"}
    )
    run = client.get(f"/api/v1/forecasts/{response.json()['id']}").json()
    assert run["status"] == "failed"
    assert run["result"] is None
    assert "no verified archive" in run["error"]
    assert client.get(f"/api/v1/forecasts/{run['id']}/export").status_code == 409


def test_download_requires_coordinates(client, monkeypatch):
    turbine = client.app.state.service.turbines["turbine-1"]
    monkeypatch.setattr(turbine, "latitude", None)
    monkeypatch.setattr(turbine, "longitude", None)
    response = client.post(
        "/api/v1/weather/fetch",
        json={"turbine_id": "turbine-1", "run_init": "2026-01-31T00:00:00Z"},
    )
    assert response.status_code == 422
    assert "coordinates" in response.json()["message"]


def test_replay_preserves_issue_and_lead_without_inventing_metrics(client, forecast_request):
    request = forecast_request | {
        "last_issued_at": "2026-02-01T00:00:00Z",
        "evaluation_start": "2026-02-01T00:00:00Z",
        "evaluation_end": "2026-03-01T00:00:00Z",
    }
    response = client.post("/api/v1/backtests", json=request)
    assert response.status_code == 202
    run = client.get(f"/api/v1/backtests/{response.json()['id']}").json()
    assert run["status"] == "succeeded"
    assert len(run["forecast_ids"]) == 2
    assert run["is_demo"] is True
    assert run["metrics"] == []
    assert run["scored_points"] == 0
    assert run["unscored_points"] == 146
    rows = list(
        csv.DictReader(io.StringIO(client.get(f"/api/v1/backtests/{run['id']}/export").text))
    )
    assert len(rows) == 146
    assert len({r["issued_at"] for r in rows}) == 2
    assert all(r["valid_time"] >= "2026-02-01" for r in rows)


def test_replay_range_is_bounded(client, forecast_request):
    response = client.post(
        "/api/v1/backtests",
        json=forecast_request
        | {
            "last_issued_at": "2026-06-01T00:00:00Z",
            "evaluation_start": "2026-02-01T00:00:00Z",
            "evaluation_end": "2026-03-01T00:00:00Z",
        },
    )
    assert response.status_code == 422
