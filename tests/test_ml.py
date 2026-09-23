from datetime import timedelta

import pytest

from wind_backend.ml import ModelPredictor, train
from wind_contracts import Observation, TrainRequest, Turbine, WeatherSnapshot

from .conftest import ISSUE, dataset_body, snapshot


def test_persistence_ignores_unavailable_and_future_observations():
    rows = dataset_body()["observations"]
    row = {**rows[0], "valid_time": ISSUE.isoformat(), "available_at": (ISSUE + timedelta(hours=1)).isoformat(), "power_normalized": 1}
    artifact = {"info": {"id": "test-model", "algorithm": "persistence", "demo": True,
        "fingerprint": "test", "trained_through": (ISSUE - timedelta(days=1)).isoformat()}, "parameters": {"turbine-1": {}}}
    predictor = ModelPredictor(artifact, [Observation.model_validate(r) for r in rows + [row]])
    points = predictor.predict(Turbine(id="turbine-1", name="One"), WeatherSnapshot.model_validate(snapshot()), ISSUE)
    assert all(p.power_normalized == rows[0]["power_normalized"] for p in points)


def test_weather_candidate_training_is_reproducible_and_uses_cutoff():
    observations = []
    weather = WeatherSnapshot.model_validate(snapshot())
    for p in weather.points:
        observations.append({"turbine_id": "turbine-1", "valid_time": p.valid_time.isoformat(),
            "available_at": p.valid_time.isoformat(), "wind_speed_ms": 8,
            "temperature_c": 10, "power_normalized": 0.4})
    observations.append({**observations[0], "valid_time": ISSUE.isoformat(), "available_at": ISSUE.isoformat()})
    dataset = {"observations": observations, "info": {"demo": True, "fingerprint": "fixture"}}
    req = TrainRequest(dataset_id="dataset-test", trained_through=ISSUE + timedelta(hours=24), algorithm="weather-ridge")
    a, b = train(req, dataset, [weather]), train(req, dataset, [weather])
    assert a["parameters"] == b["parameters"]
    assert a["info"]["training_rows"] == 24
    assert a["info"]["fingerprint"] == b["info"]["fingerprint"]
    predictor = ModelPredictor(a, [Observation.model_validate(r) for r in observations])
    with pytest.raises(Exception, match="cutoff"):
        predictor.predict(Turbine(id="turbine-1", name="One"), weather, ISSUE)
