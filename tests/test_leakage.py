import asyncio
from datetime import timedelta

import pytest
from pydantic import ValidationError
from wind_agent.interfaces import TransientWeatherError, WeatherUnavailable
from wind_agent.orchestrator import ForecastAgent
from wind_agent.weather import ArchiveWeatherProvider
from wind_backend.ml import DemoPowerCurve
from wind_contracts.models import ForecastRequest, Turbine, WeatherSnapshot

from .conftest import ISSUE, snapshot


@pytest.mark.parametrize(
    "updates",
    [
        {"available_at": ISSUE + timedelta(hours=1)},
        {"verification": "unverified", "available_at": None},
        {"points": snapshot().points[:-25]},
        {"turbine_id": "turbine-2"},
    ],
)
def test_archive_filters_unavailable_unverified_missing_or_wrong_turbine(updates):
    provider = ArchiveWeatherProvider(lambda: [snapshot(**updates)])
    request = ForecastRequest(turbine_ids=["turbine-1"], issued_at=ISSUE, weather_source="archive")
    with pytest.raises(WeatherUnavailable):
        asyncio.run(provider.fetch(Turbine(id="turbine-1", name="One"), request))


def test_verified_weather_requires_publication_evidence():
    with pytest.raises(ValidationError):
        snapshot(availability_evidence="")
    with pytest.raises(ValidationError):
        snapshot(available_at=ISSUE - timedelta(days=1))


def test_agent_does_not_trust_an_adapter_to_enforce_cutoff():
    class UnsafeProvider:
        async def fetch(self, turbine, request):
            return snapshot(available_at=ISSUE + timedelta(hours=1))

    request = ForecastRequest(turbine_ids=["turbine-1"], issued_at=ISSUE, weather_source="archive")
    with pytest.raises(ValueError, match="not available"):
        asyncio.run(
            ForecastAgent(UnsafeProvider(), DemoPowerCurve()).run(
                request, [Turbine(id="turbine-1", name="One")], lambda _: None
            )
        )


def test_agent_retries_transient_failures():
    class FlakyProvider:
        calls = 0

        async def fetch(self, turbine, request):
            self.calls += 1
            if self.calls < 3:
                raise TransientWeatherError("Temporary outage")
            return snapshot()

    provider = FlakyProvider()
    events = []
    request = ForecastRequest(turbine_ids=["turbine-1"], issued_at=ISSUE, weather_source="archive")
    result = asyncio.run(
        ForecastAgent(provider, DemoPowerCurve()).run(
            request, [Turbine(id="turbine-1", name="One")], events.append
        )
    )
    assert len(result.points) == 48
    assert len([e for e in events if e.stage == "retry"]) == 2


def test_refresh_creates_new_run_without_overwriting_old_result(client, forecast_request):
    original = snapshot()
    assert (
        client.post("/api/v1/weather/snapshots", json=original.model_dump(mode="json")).status_code
        == 201
    )
    assert (
        client.post("/api/v1/weather/snapshots", json=original.model_dump(mode="json")).status_code
        == 409
    )
    request = forecast_request | {"turbine_ids": ["turbine-1"], "weather_source": "archive"}
    created = client.post("/api/v1/forecasts", json=request).json()
    first = client.get(f"/api/v1/forecasts/{created['id']}").json()
    assert first["status"] == "succeeded"
    revised = snapshot(
        "archive-b", run_init=ISSUE - timedelta(hours=6), available_at=ISSUE - timedelta(hours=1)
    )
    revised.points[0].wind_speed_ms = 12
    assert (
        client.post("/api/v1/weather/snapshots", json=revised.model_dump(mode="json")).status_code
        == 201
    )
    refreshed = client.post(f"/api/v1/forecasts/{first['id']}/refresh").json()
    assert refreshed["changed"] is True
    assert refreshed["run"]["id"] != first["id"]
    second = client.get(f"/api/v1/forecasts/{refreshed['run']['id']}").json()
    assert second["result"]["input_fingerprint"] != first["result"]["input_fingerprint"]
    assert client.get(f"/api/v1/forecasts/{first['id']}").json() == first


def test_contract_rejects_duplicate_weather_hours():
    payload = snapshot().model_dump()
    payload["points"].append(payload["points"][0])
    with pytest.raises(ValidationError):
        WeatherSnapshot.model_validate(payload)
