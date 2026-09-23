from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from wind_backend.main import create_app
from wind_contracts import WeatherSnapshot

ISSUE = datetime(2026, 1, 31, tzinfo=timezone.utc)


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(db_path=tmp_path / "test.sqlite")) as client:
        yield client


def forecast_request(**overrides):
    return {"turbine_ids": ["turbine-1", "turbine-2"], "issued_at": ISSUE.isoformat(),
            "horizon_hours": 48, "weather_source": "demo", "model_id": "demo-power-curve", **overrides}


def snapshot(turbine_id="turbine-1", identity="weather-1", **overrides):
    body = {"id": identity, "turbine_id": turbine_id, "source": "Test fixture, not real weather evidence",
        "weather_model": "test", "run_init": ISSUE - timedelta(hours=6), "available_at": ISSUE,
        "retrieved_at": ISSUE + timedelta(days=10), "verification": "verified", "wind_height_m": 100,
        "availability_evidence": "Synthetic test fixture publication record",
        "points": [{"valid_time": ISSUE + timedelta(hours=h), "wind_speed_ms": 8, "temperature_c": 10,
                    "wind_direction_deg": 90} for h in range(1, 49)], **overrides}
    return WeatherSnapshot.model_validate(body).model_dump(mode="json")


def dataset_body(**overrides):
    return {"name": "test-observations", "demo": True, "provenance": "Artificial integration fixture",
        "observations": [{"turbine_id": turbine_id, "valid_time": (ISSUE - timedelta(hours=h)).isoformat(),
            "available_at": (ISSUE - timedelta(hours=h)).isoformat(), "wind_speed_ms": h % 16,
            "temperature_c": 10, "power_normalized": min(1, (h % 16) / 15)}
            for turbine_id in ("turbine-1", "turbine-2") for h in range(1, 97)], **overrides}
