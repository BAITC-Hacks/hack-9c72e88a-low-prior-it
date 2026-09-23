from datetime import timedelta

import pytest

from .conftest import ISSUE, dataset_body, forecast_request, snapshot


@pytest.mark.parametrize("change", [
    {"verification": "unverified", "available_at": None},
    {"available_at": (ISSUE + timedelta(hours=1)).isoformat()},
    {"verification": "unverified", "kind": "hindcast"},
])
def test_archive_rejects_late_and_unverified(client, change):
    candidate = snapshot(**change)
    assert client.post("/api/v1/weather/snapshots", json=candidate).status_code == 201
    response = client.post("/api/v1/forecasts", json=forecast_request(turbine_ids=["turbine-1"], weather_source="archive"))
    assert response.status_code == 409


def test_invalid_evidence_units_and_duplicate_hours(client):
    for change in [{"availability_evidence": " "}, {"wind_unit": "km/h"}, {"kind": "reanalysis"},
                   {"points": [snapshot()["points"][0]] * 2}]:
        body = {**snapshot(), **change}
        assert client.post("/api/v1/weather/snapshots", json=body).status_code == 422


def test_incomplete_new_run_falls_back_and_refresh_preserves_previous(client):
    older = snapshot()
    client.post("/api/v1/weather/snapshots", json=older)
    newer = snapshot(identity="incomplete", run_init=ISSUE - timedelta(hours=3))
    newer["points"] = newer["points"][:-1]
    client.post("/api/v1/weather/snapshots", json=newer)
    request = forecast_request(turbine_ids=["turbine-1"], weather_source="archive")
    first = client.post("/api/v1/forecasts", json=request).json()
    first = client.get(f"/api/v1/forecasts/{first['id']}").json()
    assert first["result"]["weather"][0]["id"] == older["id"]
    assert any(e["step"] == "fallback" for e in first["events"])
    revised = snapshot(identity="complete-new", run_init=ISSUE - timedelta(hours=3))
    revised["points"][0]["wind_speed_ms"] = 12
    client.post("/api/v1/weather/snapshots", json=revised)
    second = client.post(f"/api/v1/forecasts/{first['id']}/refresh").json()
    assert first["id"] != second["id"] and first["fingerprint"] != second["fingerprint"]
    assert client.get(f"/api/v1/forecasts/{first['id']}").json() == first
    assert client.post(f"/api/v1/forecasts/{second['id']}/refresh").json()["id"] == second["id"]


def test_training_filters_observation_latency_and_future_cutoff(client):
    body = dataset_body()
    body["observations"][0]["available_at"] = "2026-02-05T00:00:00Z"
    dataset = client.post("/api/v1/datasets", json=body).json()
    model = client.post("/api/v1/models/train", json={"dataset_id": dataset["id"], "trained_through": "2026-01-30T23:00:00Z"}).json()
    assert model["training_rows"] == 191
    request = forecast_request(model_id=model["id"], issued_at="2026-01-29T00:00:00Z")
    assert client.post("/api/v1/forecasts", json=request).status_code == 409


def test_canonical_data_rejects_clipping_naive_time_and_duplicates(client):
    body = dataset_body()
    for key, value in [("power_normalized", 1.1), ("valid_time", "2026-01-30T23:00:00"), ("wind_speed_ms", -1)]:
        original = body["observations"][0][key]
        body["observations"][0][key] = value
        assert client.post("/api/v1/datasets", json=body).status_code == 422
        body["observations"][0][key] = original
    body["observations"].append(body["observations"][0])
    assert client.post("/api/v1/datasets", json=body).status_code == 422
