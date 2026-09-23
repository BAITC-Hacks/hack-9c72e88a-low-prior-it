import asyncio

import httpx
import pytest

from wind_agent.interfaces import WeatherUnavailable
from wind_agent.weather import download_single_run
from wind_contracts.models import Turbine

from .conftest import ISSUE


def response_payload():
    return {
        "utc_offset_seconds": 0,
        "hourly_units": {"wind_speed_100m": "m/s", "temperature_2m": "°C"},
        "hourly": {"time": ["2026-01-31T01:00"], "wind_speed_100m": [8], "wind_direction_100m": [90], "temperature_2m": [-5]},
    }


def test_single_run_download_does_not_claim_historical_availability():
    async def scenario():
        def handler(request):
            assert request.url.params["run"] == "2026-01-31T00:00"
            assert request.url.params["wind_speed_unit"] == "ms"
            assert request.url.host == "single-runs-api.open-meteo.com"
            return httpx.Response(200, json=response_payload())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await download_single_run(Turbine(id="turbine-1", name="test", latitude=50, longitude=70), ISSUE, "ecmwf_ifs", client)
    result = asyncio.run(scenario())
    assert result.verification == "unverified"
    assert result.available_at is None


def test_adapter_rejects_units_or_null_weather():
    async def scenario(payload):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
            return await download_single_run(Turbine(id="turbine-1", name="test", latitude=50, longitude=70), ISSUE, "ecmwf_ifs", client)
    payload = response_payload()
    payload["hourly_units"]["wind_speed_100m"] = "km/h"
    with pytest.raises(WeatherUnavailable):
        asyncio.run(scenario(payload))
    payload = response_payload()
    payload["hourly"]["wind_speed_100m"] = [None]
    with pytest.raises(WeatherUnavailable):
        asyncio.run(scenario(payload))
