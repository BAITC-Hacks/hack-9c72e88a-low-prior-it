import httpx
import pytest

from wind_agent.interfaces import ForecastError
from wind_agent.weather import SingleRunsAdapter
from wind_contracts import Turbine, WeatherFetch


def payload():
    return {"utc_offset_seconds": 0, "hourly_units": {"wind_speed_100m": "m/s", "temperature_2m": "°C", "wind_direction_100m": "°"},
        "hourly": {"time": ["2026-01-31T00:00", "2026-01-31T01:00"], "wind_speed_100m": [7, 8],
                   "temperature_2m": [2, 3], "wind_direction_100m": [90, 100]}}


def test_download_retries_and_caches_unverified_candidate(tmp_path):
    calls, events, waits = [], [], []

    def handle(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json=payload())

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        adapter = SingleRunsAdapter(tmp_path, client=client, sleep=waits.append)
        result = adapter.fetch(WeatherFetch(turbine_id="turbine-1", run_init="2026-01-31T00:00:00Z"),
            Turbine(id="turbine-1", name="One", latitude=43.6, longitude=78.5), events.append)
    assert len(calls) == 3 and waits == [1, 2] and len(events) == 2
    assert result.available_at is None and result.verification == "unverified"
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert calls[0].url.params["wind_speed_unit"] == "ms"


def test_provider_failure_is_bounded(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))) as client:
        adapter = SingleRunsAdapter(tmp_path, client=client, sleep=lambda s: None)
        with pytest.raises(ForecastError) as exc:
            adapter.fetch(WeatherFetch(turbine_id="turbine-1", run_init="2026-01-31T00:00:00Z"),
                          Turbine(id="turbine-1", name="One", latitude=43.6, longitude=78.5))
        assert exc.value.status == 503


def test_units_are_not_silently_reinterpreted(tmp_path):
    body = payload()
    body["hourly_units"]["wind_speed_100m"] = "km/h"
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))) as client:
        with pytest.raises(ForecastError, match="units"):
            SingleRunsAdapter(tmp_path, client=client).fetch(
                WeatherFetch(turbine_id="turbine-1", run_init="2026-01-31T00:00:00Z"),
                Turbine(id="turbine-1", name="One", latitude=43.6, longitude=78.5))
