import asyncio
import csv
from datetime import UTC, datetime, timedelta

import pytest
from wind_agent.ecmwf_archive import (
    ECMWF_PUBLICATION_DELAY_HOURS,
    import_ecmwf_archive,
    load_ecmwf_snapshots,
)
from wind_agent.interfaces import WeatherUnavailable
from wind_agent.weather import ArchiveWeatherProvider
from wind_contracts.models import ForecastRequest, Turbine

RUN = datetime(2026, 1, 31, tzinfo=UTC)
IMPORTED_AT = datetime(2026, 9, 23, tzinfo=UTC)


def archive_rows(run=RUN, loc=1):
    return [
        {
            "run_utc": run.strftime("%Y-%m-%d %H:%M"),
            "loc": loc,
            "valid_utc": (run + timedelta(hours=lead)).strftime("%Y-%m-%d %H:%M"),
            "lead_h": lead,
            "wind_speed_100m": 8.5,
            "wind_direction_100m": 215,
            "temperature_2m": -3.5,
        }
        for lead in range(72)
    ]


def write_archive(tmp_path, rows):
    path = tmp_path / "archive.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_default_import_does_not_claim_availability(tmp_path):
    path = write_archive(tmp_path, archive_rows())
    snapshot = load_ecmwf_snapshots(path, retrieved_at=IMPORTED_AT)[0]
    assert snapshot.verification == "unverified"
    assert snapshot.available_at is None
    assert snapshot.availability_evidence is None
    assert snapshot.retrieved_at == IMPORTED_AT


def test_explicit_reconstruction_uses_only_00utc_and_discloses_assumptions(tmp_path):
    rows = archive_rows() + archive_rows(loc=2) + archive_rows(run=RUN + timedelta(hours=6))
    path = write_archive(tmp_path, rows)
    imported = import_ecmwf_archive(
        path,
        accept_schedule_assumption=True,
        retrieved_at=IMPORTED_AT,
    )
    assert len(imported.snapshots) == 2
    for snapshot in imported.snapshots:
        assert snapshot.run_init == RUN
        assert snapshot.available_at == RUN + timedelta(hours=ECMWF_PUBLICATION_DELAY_HOURS)
        assert snapshot.verification == "verified"
        assert "not per-run historical publication proof" in snapshot.availability_evidence
        assert "hindcasts" in snapshot.availability_evidence
        assert "current schedule does not establish historical" in snapshot.availability_evidence
        assert snapshot.wind_height_m == 100
        assert snapshot.points[13].valid_time == RUN + timedelta(hours=13)
        assert snapshot.points[13].wind_speed_ms == 8.5
        assert snapshot.points[13].wind_direction_deg == 215
        assert snapshot.points[13].temperature_c == -3.5
    assert imported.metadata["counts"]["excluded_other_cycle_rows"] == 72
    assert imported.metadata["historical_operational_availability_proven"] is False
    assert imported.metadata["hindcast"] is True


def test_runtime_enforces_delay_and_complete_48_hour_coverage(tmp_path):
    snapshots = load_ecmwf_snapshots(
        write_archive(tmp_path, archive_rows()),
        accept_schedule_assumption=True,
    )
    provider = ArchiveWeatherProvider(lambda: snapshots)
    turbine = Turbine(id="turbine-1", name="First turbine")

    def fetch(hour):
        return asyncio.run(
            provider.fetch(
                turbine,
                ForecastRequest(
                    turbine_ids=[turbine.id],
                    issued_at=RUN + timedelta(hours=hour),
                    horizon_hours=48,
                    weather_source="archive",
                ),
            )
        )

    with pytest.raises(WeatherUnavailable):
        fetch(9)
    assert fetch(10).id == snapshots[0].id
    assert fetch(12).id == snapshots[0].id
    # Yesterday's 00 UTC run has leads 0..71, not the 72 required at midnight.
    with pytest.raises(WeatherUnavailable):
        fetch(24)


def test_missing_weather_is_reported_without_filling(tmp_path):
    missing = archive_rows(loc=2)
    for row in missing:
        row["wind_speed_100m"] = ""
    rows = archive_rows() + missing
    rows[60]["temperature_2m"] = ""
    imported = import_ecmwf_archive(
        write_archive(tmp_path, rows),
        accept_schedule_assumption=True,
    )
    assert len(imported.snapshots) == 1
    assert len(imported.snapshots[0].points) == 71
    assert imported.metadata["counts"]["empty_groups_skipped"] == 1
    assert imported.metadata["counts"]["missing_required_weather_rows"] == 73
    provider = ArchiveWeatherProvider(lambda: imported.snapshots)
    with pytest.raises(WeatherUnavailable):
        asyncio.run(
            provider.fetch(
                Turbine(id="turbine-1", name="One"),
                ForecastRequest(
                    turbine_ids=["turbine-1"],
                    issued_at=RUN + timedelta(hours=12),
                    weather_source="archive",
                    horizon_hours=48,
                ),
            )
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lead_h", 2),
        ("lead_h", 0.5),
        ("loc", 3),
        ("wind_speed_100m", "nan"),
        ("wind_direction_100m", 361),
        ("valid_utc", "2026-01-31 00:30"),
    ],
)
def test_malformed_source_is_rejected(tmp_path, field, value):
    rows = archive_rows()
    rows[0][field] = value
    with pytest.raises(ValueError):
        load_ecmwf_snapshots(write_archive(tmp_path, rows), accept_schedule_assumption=True)


def test_duplicate_hours_are_rejected_and_ids_are_immutable(tmp_path):
    rows = archive_rows()
    path = write_archive(tmp_path, rows)
    first = load_ecmwf_snapshots(path, accept_schedule_assumption=True)[0]
    again = load_ecmwf_snapshots(path, accept_schedule_assumption=True)[0]
    candidate = load_ecmwf_snapshots(path)[0]
    assert first.id == again.id
    assert candidate.id != first.id
    rows[0]["wind_speed_100m"] = 9
    assert (
        load_ecmwf_snapshots(
            write_archive(tmp_path, rows),
            accept_schedule_assumption=True,
        )[0].id
        != first.id
    )
    with pytest.raises(ValueError, match="Duplicate"):
        load_ecmwf_snapshots(write_archive(tmp_path, rows + [rows[0]]))


def test_date_filter_requires_explicit_timezone_and_has_exclusive_end(tmp_path):
    rows = archive_rows() + archive_rows(run=RUN + timedelta(days=1))
    path = write_archive(tmp_path, rows)
    imported = import_ecmwf_archive(path, start=RUN, end=RUN + timedelta(days=1))
    assert len(imported.snapshots) == 1
    assert imported.snapshots[0].run_init == RUN
    with pytest.raises(ValueError, match="explicit timezone"):
        import_ecmwf_archive(path, start=RUN.replace(tzinfo=None))


def test_bundled_archive_has_full_daily_february_replay_coverage():
    imported = import_ecmwf_archive(accept_schedule_assumption=True, retrieved_at=IMPORTED_AT)
    assert len(imported.snapshots) == 1424
    assert imported.metadata["counts"]["empty_groups_skipped"] == 2
    assert imported.metadata["missing_run_dates"] == [
        "2025-08-05",
        "2025-08-06",
        "2025-08-08",
        "2025-08-09",
    ]
    index = {(snapshot.run_init, snapshot.turbine_id): snapshot for snapshot in imported.snapshots}
    for day in range(29):
        run = RUN + timedelta(days=day)
        for turbine_id in ("turbine-1", "turbine-2"):
            snapshot = index[(run, turbine_id)]
            issue = run + timedelta(hours=12)
            assert snapshot.available_at <= issue
            targets = {issue + timedelta(hours=lead) for lead in range(1, 49)}
            assert targets <= {point.valid_time for point in snapshot.points}
