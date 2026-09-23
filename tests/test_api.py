import csv
import io

from fastapi.testclient import TestClient

from wind_backend.main import create_app

from .conftest import dataset_body, forecast_request, snapshot


def test_complete_demo_and_restart(tmp_path):
    path = tmp_path / "persistent.sqlite"
    with TestClient(create_app(db_path=path)) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert len(client.get("/api/v1/turbines").json()) == 2
        queued = client.post("/api/v1/forecasts", json=forecast_request())
        assert queued.status_code == 202
        assert queued.json()["status"] == "queued"
        run_id = queued.json()["id"]
        result = client.get(f"/api/v1/forecasts/{run_id}").json()
        assert result["status"] == "succeeded"
        assert result["result"]["demo"]
        assert len(result["result"]["points"]) == 96
        assert result["result"]["points"][0]["lead_hours"] == 1
        assert client.post(f"/api/v1/forecasts/{run_id}/refresh").json()["id"] == run_id
        assert len(client.get(f"/api/v1/forecasts/{run_id}/events").json()) >= 4
        rows = list(csv.DictReader(io.StringIO(client.get(f"/api/v1/forecasts/{run_id}/export").text)))
        assert len(rows) == 96 and all(r["verification"] == "demo" for r in rows)
    with TestClient(create_app(db_path=path)) as client:
        assert client.get(f"/api/v1/forecasts/{run_id}").json() == result


def test_dataset_training_and_immutable_weather(client):
    data = client.post("/api/v1/datasets", json=dataset_body())
    assert data.status_code == 201
    model = client.post("/api/v1/models/train", json={"dataset_id": data.json()["id"], "trained_through": "2026-01-30T23:00:00Z"})
    assert model.status_code == 201
    assert model.json()["training_rows"] == 192
    assert model.json()["demo"]
    response = client.post("/api/v1/forecasts", json=forecast_request(model_id=model.json()["id"]))
    run = client.get(f"/api/v1/forecasts/{response.json()['id']}").json()
    assert run["status"] == "succeeded" and run["result"]["demo"]
    assert client.post("/api/v1/weather/snapshots", json=snapshot()).status_code == 201
    assert client.post("/api/v1/weather/snapshots", json=snapshot()).status_code == 409


def test_errors_have_consistent_shape(client):
    requests = [client.get("/api/v1/forecasts/missing"),
                client.post("/api/v1/forecasts", json=forecast_request(issued_at="2026-01-31T00:00:00")),
                client.post("/api/v1/forecasts", json=forecast_request(turbine_ids=["unknown"])),
                client.post("/api/v1/forecasts", json=forecast_request(weather_source="archive"))]
    assert [r.status_code for r in requests] == [404, 422, 404, 409]
    assert all(set(r.json()) == {"code", "message"} for r in requests)


def test_replay_filters_target_hours_and_missing_actuals(client):
    response = client.post("/api/v1/backtests", json={**forecast_request(), "end_issue_at": "2026-02-28T00:00:00Z",
        "evaluation_start": "2026-02-01T00:00:00Z", "evaluation_end": "2026-03-01T00:00:00Z"})
    assert response.status_code == 202
    run = client.get(f"/api/v1/backtests/{response.json()['id']}").json()
    assert run["status"] == "succeeded" and run["completed"] == 29
    assert len(run["metrics"]) == 4
    assert all(m["mae"] is None and m["missing"] == m["predicted"] for m in run["metrics"])
    rows = list(csv.DictReader(io.StringIO(client.get(f"/api/v1/backtests/{run['id']}/export").text)))
    assert all("2026-02-01" <= r["valid_time"] < "2026-03-01" for r in rows)
    assert len({(r["issued_at"], r["valid_time"], r["turbine_id"]) for r in rows}) == len(rows)


def test_restart_marks_unfinished_jobs_failed(tmp_path):
    path = tmp_path / "restart.sqlite"
    with TestClient(create_app(db_path=path)) as client:
        from wind_contracts import ForecastRequest
        queued, _ = client.app.state.service.queue_forecast(ForecastRequest.model_validate(forecast_request()))
    with TestClient(create_app(db_path=path)) as client:
        run = client.get(f"/api/v1/forecasts/{queued.id}").json()
        assert run["status"] == "failed" and run["error"]["code"] == "process_restarted"
        assert client.get(f"/api/v1/forecasts/{queued.id}/export").status_code == 409
        retry = client.post("/api/v1/forecasts", json=forecast_request()).json()
        assert retry["id"] != queued.id


def test_scoring_uses_actuals_after_predictions(client):
    body = dataset_body()
    body["observations"] = [{**body["observations"][0], "valid_time": "2026-02-01T00:00:00Z",
        "available_at": "2026-02-03T00:00:00Z", "power_normalized": 0.5}]
    data = client.post("/api/v1/datasets", json=body).json()
    response = client.post("/api/v1/backtests", json={**forecast_request(), "end_issue_at": "2026-01-31T00:00:00Z",
        "evaluation_start": "2026-02-01T00:00:00Z", "evaluation_end": "2026-02-02T00:00:00Z", "actual_dataset_id": data["id"]})
    run = client.get(f"/api/v1/backtests/{response.json()['id']}").json()
    assert sum(m["scored"] for m in run["metrics"]) == 1
    assert next(m for m in run["metrics"] if m["scored"])["mae"] is not None
