import asyncio
from datetime import timedelta

import pytest
from wind_agent.analysis import summarize_forecast
from wind_agent.orchestrator import ForecastAgent, fingerprint
from wind_agent.weather import DemoWeatherProvider
from wind_backend.ml import DemoPowerCurve
from wind_contracts.models import ForecastPoint, ForecastRequest, Turbine

from .conftest import ISSUE


def points(powers, *, turbine_id="turbine-1", leads=None):
    return [
        ForecastPoint(
            turbine_id=turbine_id,
            valid_time=ISSUE + timedelta(hours=lead),
            lead_hours=lead,
            power_normalized=power,
        )
        for lead, power in zip(leads or range(1, len(powers) + 1), powers, strict=True)
    ]


def test_analysis_reports_exact_means_peaks_and_adjacent_hour_changes():
    rows = points([0.25, 0.75, 0.5, 1.0, 0.5])
    before = [point.model_dump() for point in rows]
    message = summarize_forecast(list(reversed(rows)), is_demo=True)[0]

    assert "DEMO / PROVISIONAL: turbine-1; leads 1-5 h; 5 hourly means" in message
    assert "Mean 60.00% of normalized power; peak 100.00% at lead 4 h" in message
    # The two equal rises select the earlier one, independently of input ordering.
    assert "rise +50.00 percentage points: lead 1 to 2 h" in message
    assert "drop -50.00 percentage points: lead 4 to 5 h" in message
    assert "interval ends 2026-01-31T01:00Z to 2026-01-31T02:00Z" in message
    assert [point.model_dump() for point in rows] == before


def test_analysis_keeps_turbines_separate_and_flat_forecast_stable():
    rows = points([1, 1], turbine_id="turbine-2") + points([0.25, 0.25])
    messages = summarize_forecast(rows, is_demo=False)

    assert messages[0].startswith("Forecast analysis: turbine-1;")
    assert "Mean 25.00%" in messages[0]
    assert "Mean 100.00%" in messages[1]
    assert all("Stable across adjacent hourly means" in message for message in messages)
    assert all("peak" in message and "at lead 1 h" in message for message in messages)
    assert all("Largest hourly" not in message for message in messages)


def test_analysis_does_not_bridge_missing_hours():
    message = summarize_forecast(points([0, 1], leads=[1, 3]), is_demo=False)[0]
    assert "Hourly change unavailable: no adjacent hourly intervals." in message
    assert "Hourly changes exclude gaps" in message
    assert "Largest hourly" not in message
    assert summarize_forecast([], is_demo=False) == []


@pytest.mark.parametrize("powers,label", [([0, 0.5, 1], "drop"), ([1, 0.5, 0], "rise")])
def test_monotonic_forecast_does_not_invent_opposite_ramp(powers, label):
    message = summarize_forecast(points(powers), is_demo=False)[0]
    assert f"No hourly {label} in the forecast." in message


@pytest.mark.parametrize("horizon", [24, 48])
def test_agent_emits_analysis_without_changing_predictions_or_fingerprint(horizon):
    request = ForecastRequest(
        turbine_ids=["turbine-1", "turbine-2"], issued_at=ISSUE, horizon_hours=horizon
    )
    turbines = [Turbine(id=identifier, name=identifier) for identifier in request.turbine_ids]
    predictor = DemoPowerCurve()
    events = []
    result = asyncio.run(
        ForecastAgent(DemoWeatherProvider(), predictor).run(request, turbines, events.append)
    )
    expected = [
        point
        for turbine, snapshot in zip(turbines, result.snapshots, strict=True)
        for point in predictor.predict(turbine, snapshot.points, request.issued_at)
    ]

    assert result.points == expected
    assert result.input_fingerprint == fingerprint(
        request, result.snapshots, predictor.info.model_dump(mode="json")
    )
    summaries = [
        event.message
        for event in events
        if event.stage == "analyse" and "hourly means" in event.message
    ]
    assert len(summaries) == 2
    assert all(message.startswith("DEMO / PROVISIONAL:") for message in summaries)
    assert all(f"leads 1-{horizon} h" in message for message in summaries)
    assert all(
        "Largest hourly rise" in message and "Largest hourly drop" in message
        for message in summaries
    )
    assert events[-1].stage == "complete"
