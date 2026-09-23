from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from wind_backend.config import Settings
from wind_backend.main import create_app
from wind_contracts.models import WeatherPoint, WeatherSnapshot

ROOT = Path(__file__).resolve().parents[1]
ISSUE = datetime(2026, 1, 31, tzinfo=UTC)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        tmp_path / "test.sqlite3", ROOT / "config/turbines.example.json", tmp_path / "models"
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as value:
        yield value


@pytest.fixture
def forecast_request():
    return {
        "turbine_ids": ["turbine-1", "turbine-2"],
        "issued_at": ISSUE.isoformat(),
        "horizon_hours": 48,
        "weather_source": "demo",
        "model_id": "demo-power-curve",
    }


def snapshot(identifier="archive-a", **updates):
    payload = {
        "id": identifier,
        "turbine_id": "turbine-1",
        "source": "external-archive",
        "weather_model": "test-fixture",
        "run_init": ISSUE - timedelta(hours=12),
        "retrieved_at": ISSUE + timedelta(days=200),
        "available_at": ISSUE - timedelta(hours=6),
        "verification": "verified",
        "availability_evidence": "Unit-test fixture only; not a real forecast archive.",
        "wind_height_m": 100,
        "points": [
            WeatherPoint(
                valid_time=ISSUE + timedelta(hours=i),
                wind_speed_ms=8,
                wind_direction_deg=90,
                temperature_c=-5,
            )
            for i in range(1, 73)
        ],
    }
    payload.update(updates)
    return WeatherSnapshot.model_validate(payload)
