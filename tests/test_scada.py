from datetime import timedelta
from statistics import pstdev

import pytest
from pydantic import ValidationError
from wind_agent.scada import aggregate_hourly, inspect_scada_csv, parse_scada_csv, profile_scada
from wind_agent.temporal import (
    forecast_lead,
    observations_as_of,
    validate_chronological_split,
    validate_weather_timing,
)
from wind_contracts.scada import ScadaReading

from .conftest import ISSUE


def reading(minutes=0, **updates):
    moment = ISSUE + timedelta(minutes=minutes)
    return ScadaReading.model_validate(
        {
            "turbine_id": "turbine-1",
            "valid_time": moment,
            "available_at": moment,
            "wind_speed_ms": 8,
            "temperature_c": -5,
            "power_normalized": 0.2,
        }
        | updates
    )


def hour_rows():
    return [
        reading(-50 + 10 * i, wind_speed_ms=5 + i, power_normalized=i / 10, temperature_c=-5 + i)
        for i in range(6)
    ]


def test_hour_end_statistics_and_backend_conversion():
    rows = hour_rows()
    rows[-1] = reading(
        0,
        wind_speed_ms=10,
        power_normalized=0.5,
        temperature_c=0,
        available_at=ISSUE + timedelta(minutes=7),
    )
    hourly = aggregate_hourly(reversed(rows))[0]
    assert hourly.valid_time == ISSUE
    assert hourly.available_at == ISSUE + timedelta(minutes=7)
    assert hourly.complete and hourly.sample_count == 6
    assert hourly.wind_mean == 7.5
    assert (hourly.wind_min, hourly.wind_max) == (5, 10)
    assert hourly.wind_std == pytest.approx(pstdev(range(5, 11)))
    assert hourly.power_mean == pytest.approx(0.25)
    assert hourly.power_std == pytest.approx(pstdev([i / 10 for i in range(6)]))
    assert (hourly.power_min, hourly.power_max) == (0, 0.5)
    assert hourly.temperature_mean == -2.5
    assert hourly.temperature_std == pytest.approx(pstdev(range(-5, 1)))
    observation = hourly.to_observation()
    assert observation.power_normalized == hourly.power_mean
    assert observation.available_at == hourly.available_at


def test_midnight_boundary_and_turbine_isolation():
    hours = aggregate_hourly(
        [reading(0), reading(10), reading(0, turbine_id="turbine-2", power_normalized=0.8)]
    )
    assert [(row.turbine_id, row.valid_time) for row in hours] == [
        ("turbine-1", ISSUE),
        ("turbine-1", ISSUE + timedelta(hours=1)),
        ("turbine-2", ISSUE),
    ]
    assert hours[-1].power_mean == 0.8
    assert hours[0].power_std == 0
    with pytest.raises(ValueError, match="Incomplete"):
        hours[0].to_observation()


def test_as_of_aggregation_excludes_late_and_future_readings_before_statistics():
    rows = hour_rows()
    rows[0] = reading(-50, power_normalized=1, available_at=ISSUE + timedelta(hours=1))
    historical = aggregate_hourly(rows, forecast_origin=ISSUE)
    # Changing unavailable data cannot change this origin's features.
    changed = rows + [reading(10, power_normalized=1), reading(0, turbine_id="turbine-2")]
    actual = aggregate_hourly(changed, forecast_origin=ISSUE)
    assert actual[0] == historical[0]
    assert actual[0].sample_count == 5
    assert actual[0].power_mean == pytest.approx(0.3)
    assert actual[0].available_at == ISSUE
    assert (
        observations_as_of(aggregate_hourly(rows), turbine_id="turbine-1", forecast_origin=ISSUE)
        == []
    )
    assert aggregate_hourly([reading(10)], forecast_origin=ISSUE + timedelta(minutes=20)) == []


def test_profile_counts_missing_slots_zero_power_and_delay():
    rows = [reading(-20, power_normalized=0), reading(0, available_at=ISSUE + timedelta(minutes=1))]
    profile = profile_scada(rows)["turbine-1"]
    assert profile["missing_slots"] == 1
    assert profile["zero_power_rows"] == 1
    assert profile["delayed_rows"] == 1
    assert profile["hour_coverage"] == {2: 1}


@pytest.mark.parametrize("rows", [[reading(), reading()], [reading(1)]])
def test_aggregation_rejects_duplicates_and_irregular_sampling(rows):
    with pytest.raises(ValueError):
        aggregate_hourly(rows)


@pytest.mark.parametrize("interval", [0, -10, 7, 10.0, True])
def test_invalid_sampling_interval(interval):
    with pytest.raises(ValueError, match="divisor"):
        aggregate_hourly([], interval_minutes=interval)


@pytest.mark.parametrize(
    "updates",
    [
        {"valid_time": "2026-01-31T00:00:00"},
        {"available_at": ISSUE - timedelta(seconds=1)},
        {"wind_speed_ms": float("nan")},
        {"temperature_c": float("inf")},
        {"power_normalized": -0.1},
        {"power_normalized": 1.1},
        {"power_normalized": None},
    ],
)
def test_invalid_readings_are_rejected(updates):
    with pytest.raises(ValidationError):
        reading(**updates)


def test_csv_inspection_reports_errors_and_ingestion_fails_closed(tmp_path):
    path = tmp_path / "readings.csv"
    header = "turbine_id,valid_time,available_at,wind_speed_ms,temperature_c,power_normalized\n"
    good = "turbine-1,2026-01-31T05:00:00+05:00,2026-01-31T05:00:00+05:00,8,-5,0.2\n"
    path.write_text(
        header + good + good + good.replace(",0.2", ",") + good.replace(",8,", ",NaN,"),
        encoding="utf-8-sig",
    )
    report = inspect_scada_csv(path)
    assert report.source_rows == 4
    assert len(report.rows) == 1
    assert report.rows[0].valid_time == ISSUE
    assert [issue.line for issue in report.issues] == [3, 4, 5]
    with pytest.raises(ValueError, match="3 invalid SCADA rows"):
        parse_scada_csv(path)
    path.write_text(header + good, encoding="utf-8")
    assert parse_scada_csv(path) == report.rows


def test_csv_explicit_mapping_and_missing_availability(tmp_path):
    path = tmp_path / "source.csv"
    path.write_text(
        "asset;time;received;wind;temp;power;unused\n"
        "turbine-1;2026-01-31T00:00:00Z;2026-01-31T00:00:00Z;8;-5;0.2;x\n",
        encoding="utf-8",
    )
    columns = dict(
        zip(
            ScadaReading.model_fields,
            ["asset", "time", "received", "wind", "temp", "power"],
            strict=True,
        )
    )
    assert parse_scada_csv(path, columns=columns, delimiter=";")[0] == reading()
    with pytest.raises(ValueError, match="headers"):
        parse_scada_csv(path, delimiter=";")
    path.write_text(
        "turbine_id,valid_time,wind_speed_ms,temperature_c,power_normalized\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="headers"):
        parse_scada_csv(path)


@pytest.mark.parametrize("lead", [1, 24, 25, 48])
def test_weather_timing_accepts_exact_origin_and_supported_leads(lead):
    assert (
        validate_weather_timing(
            forecast_origin=ISSUE,
            target_time=ISSUE + timedelta(hours=lead),
            weather_issue_time=ISSUE,
            available_at=ISSUE,
        )
        == lead
    )


@pytest.mark.parametrize("lead", [-1, 0, 49, 0.5])
def test_invalid_target_times(lead):
    with pytest.raises(ValueError):
        forecast_lead(ISSUE, ISSUE + timedelta(hours=lead))


def test_temporal_helpers_reject_naive_origin_and_future_publication():
    with pytest.raises(ValueError):
        observations_as_of([], turbine_id="turbine-1", forecast_origin=ISSUE.replace(tzinfo=None))
    with pytest.raises(ValueError):
        validate_weather_timing(
            forecast_origin=ISSUE,
            target_time=ISSUE + timedelta(hours=1),
            weather_issue_time=ISSUE - timedelta(hours=6),
            available_at=ISSUE + timedelta(seconds=1),
        )
    with pytest.raises(ValueError):
        validate_weather_timing(
            forecast_origin=ISSUE,
            target_time=ISSUE + timedelta(hours=1),
            weather_issue_time=ISSUE + timedelta(hours=1),
            available_at=ISSUE,
        )


def test_chronological_validation_checks_training_target_and_availability_cutoffs():
    valid = [reading(60)]
    validate_chronological_split([reading()], valid, trained_through=ISSUE, validation_origin=ISSUE)
    for training in [[reading(10)], [reading(0, available_at=ISSUE + timedelta(minutes=1))], []]:
        with pytest.raises(ValueError):
            validate_chronological_split(
                training, valid, trained_through=ISSUE, validation_origin=ISSUE
            )
    with pytest.raises(ValueError):
        validate_chronological_split(
            [reading()], [reading()], trained_through=ISSUE, validation_origin=ISSUE
        )
