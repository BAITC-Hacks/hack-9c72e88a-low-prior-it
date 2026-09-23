from datetime import timedelta

import pytest

from wind_backend.evaluation import evaluate
from wind_backend.ml import BinnedPowerCurve
from wind_contracts.models import ForecastPoint, Observation

from .conftest import ISSUE


def observation(power, valid_time, available_at=None):
    return Observation(turbine_id="turbine-1", valid_time=valid_time, available_at=available_at or valid_time, wind_speed_ms=8, temperature_c=-5, power_normalized=power)


def test_training_excludes_future_targets_and_late_arriving_measurements():
    rows = [
        observation(0.2, ISSUE - timedelta(hours=2)),
        observation(0.9, ISSUE - timedelta(hours=1), ISSUE + timedelta(hours=1)),
        observation(1, ISSUE + timedelta(hours=1)),
    ]
    model = BinnedPowerCurve.fit("model-a", "dataset-a", rows, ISSUE)
    assert model.info.training_rows == 1
    assert model.curves["turbine-1"]["8"] == 0.2


def test_model_cutoff_checked_before_forecast(client, forecast_request):
    upload = client.post("/api/v1/datasets", json={"name": "test observations", "observations": [observation(0.2, ISSUE).model_dump(mode="json")]})
    assert upload.status_code == 201
    trained = client.post("/api/v1/models/train", json={"dataset_id": upload.json()["id"], "trained_through": (ISSUE + timedelta(days=1)).isoformat()})
    assert trained.status_code == 201
    response = client.post("/api/v1/forecasts", json=forecast_request | {"model_id": trained.json()["id"], "turbine_ids": ["turbine-1"]})
    assert response.status_code == 422


def test_evaluation_keeps_horizons_and_handles_zero_power():
    valid = ISSUE + timedelta(hours=25)
    points = [
        ForecastPoint(turbine_id="turbine-1", valid_time=valid, lead_hours=1, power_normalized=0.2),
        ForecastPoint(turbine_id="turbine-1", valid_time=valid, lead_hours=25, power_normalized=0.4),
        ForecastPoint(turbine_id="turbine-1", valid_time=valid + timedelta(hours=1), lead_hours=26, power_normalized=0.5),
    ]
    metrics, scored, missing = evaluate(points, [observation(0, valid)])
    assert scored == 2 and missing == 1
    assert [row.horizon for row in metrics] == ["1-24", "25-48"]
    assert metrics[0].mae == pytest.approx(0.2)
    assert metrics[1].rmse == pytest.approx(0.4)


def test_duplicate_observations_rejected(client):
    row = observation(0.2, ISSUE).model_dump(mode="json")
    response = client.post("/api/v1/datasets", json={"name": "duplicates", "observations": [row, row]})
    assert response.status_code == 422
