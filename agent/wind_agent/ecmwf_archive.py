"""Explicit, offline import of the bundled 00 UTC ECMWF hindcast reconstruction.

Verification here means acceptance of the documented schedule assumption, not
proof that these hindcast values existed at the historical issue time. Network
downloaders deliberately do not call this importer or inherit its assumption.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from wind_contracts.models import WeatherPoint, WeatherSnapshot

DEFAULT_ARCHIVE_PATH = (
    Path(__file__).resolve().parents[2] / "data/weather/ecmwf_ifs_single_runs.csv.gz"
)
ECMWF_PUBLICATION_DELAY_HOURS = 10
ECMWF_ISSUE_HOUR_UTC = 12
ECMWF_RUN_HOUR_UTC = 0
ECMWF_IMPORT_PROTOCOL = "ecmwf-00utc-hindcast-schedule-10h-v1"
ECMWF_SCHEDULE_URL = "https://confluence.ecmwf.int/pages/viewpage.action?pageId=600793086"
ECMWF_OPEN_DATA_URL = "https://www.ecmwf.int/en/forecasts/datasets/open-data"
OPEN_METEO_SINGLE_RUNS_URL = "https://open-meteo.com/en/docs/single-runs-api"
DOCUMENTATION_REVIEWED_ON = "2026-09-23"
AVAILABILITY_BASIS = (
    "Schedule-assumed hindcast reconstruction: run_init + 10 hours; "
    "not per-run historical publication proof."
)
ARCHIVE_LIMITATIONS = [
    "Open-Meteo identifies the early ECMWF IFS archive as Cycle 49R1 hindcasts. "
    "These values are not proven to be the contemporaneous operational forecasts.",
    "Publication time is inferred from the ECMWF dissemination/open-data schedule "
    "reviewed in September 2026, not measured for each historical run. The current "
    "schedule is not evidence of the schedule or outages in 2024-2026.",
    "A 10-hour publication delay is a conservative reconstruction assumption, "
    "not an Open-Meteo historical service guarantee.",
    "The compiled CSV does not retain individual API response metadata. Units "
    "are supported by the collector's explicit m/s and GMT request parameters.",
    "Both turbines can share one NWP grid cell; 100 m forecast wind is not a "
    "measurement of the unknown turbine hub height.",
]
_REQUIRED_COLUMNS = {
    "run_utc",
    "loc",
    "valid_utc",
    "lead_h",
    "wind_speed_100m",
    "wind_direction_100m",
    "temperature_2m",
}


@dataclass(frozen=True)
class ArchiveImport:
    snapshots: list[WeatherSnapshot]
    metadata: dict


def _utc_hour(value: str, field: str) -> datetime:
    """Naive values are UTC only because the source column explicitly says UTC."""
    moment = datetime.fromisoformat(value)
    moment = moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
    if moment.minute or moment.second or moment.microsecond:
        raise ValueError(f"{field} must be aligned to a UTC hour")
    return moment


def _boundary(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("Import date boundaries must have an explicit timezone")
    return value.astimezone(UTC) if value is not None else None


def import_ecmwf_archive(
    path: str | Path = DEFAULT_ARCHIVE_PATH,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    accept_schedule_assumption: bool = False,
    retrieved_at: datetime | None = None,
) -> ArchiveImport:
    """Return 00 UTC snapshots and auditable metadata; ``end`` is exclusive.

    Default candidates remain unverified with no claimed availability. Opting in
    records the explicit hindcast/schedule assumption required by this offline
    research protocol. Missing weather is never filled from observations.
    ``retrieved_at`` records local import time, not historical API retrieval.
    """
    path = Path(path)
    start, end = _boundary(start), _boundary(end)
    if start is not None and end is not None and start >= end:
        raise ValueError("Import end must be after start")
    imported_at = _boundary(retrieved_at) or datetime.now(UTC)
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    protocol_token = hashlib.sha256(ECMWF_IMPORT_PROTOCOL.encode()).hexdigest()[:8]
    groups: dict[tuple[datetime, int], list[WeatherPoint]] = defaultdict(list)
    seen: set[tuple[datetime, int, datetime]] = set()
    missing_rows = other_cycle_rows = selected_rows = 0
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not _REQUIRED_COLUMNS.issubset(reader.fieldnames or []):
            raise ValueError("ECMWF archive is missing required columns")
        for row in reader:
            run_init = _utc_hour(row["run_utc"], "run_utc")
            if (start is not None and run_init < start) or (end is not None and run_init >= end):
                continue
            if run_init.hour != ECMWF_RUN_HOUR_UTC:
                other_cycle_rows += 1
                continue
            selected_rows += 1
            if row["loc"] not in {"1", "2"}:
                raise ValueError(f"Unknown ECMWF location: {row['loc']}")
            loc = int(row["loc"])
            valid_time = _utc_hour(row["valid_utc"], "valid_utc")
            lead = float(row["lead_h"])
            if not math.isfinite(lead) or not lead.is_integer() or not 0 <= lead <= 71:
                raise ValueError("Bundled ECMWF lead_h must be an integer from 0 through 71")
            if valid_time != run_init + timedelta(hours=lead):
                raise ValueError("ECMWF valid_utc does not equal run_utc + lead_h")
            key = (run_init, loc, valid_time)
            if key in seen:
                raise ValueError("Duplicate ECMWF run/location/valid-time row")
            seen.add(key)
            points = groups[(run_init, loc)]
            fields = ("wind_speed_100m", "wind_direction_100m", "temperature_2m")
            if any(not row[field].strip() for field in fields):
                missing_rows += 1
                continue
            points.append(
                WeatherPoint(
                    valid_time=valid_time,
                    wind_speed_ms=float(row["wind_speed_100m"]),
                    wind_direction_deg=float(row["wind_direction_100m"]),
                    temperature_c=float(row["temperature_2m"]),
                )
            )

    snapshots = []
    mode = "assumed" if accept_schedule_assumption else "candidate"
    for (run_init, loc), points in sorted(groups.items()):
        if not points:
            continue
        evidence = None
        if accept_schedule_assumption:
            evidence = (
                f"Explicit offline import protocol={ECMWF_IMPORT_PROTOCOL}; "
                f"source=Open-Meteo Single Runs, ECMWF IFS; run_init={run_init.isoformat()}; "
                f"CSV sha256={source_sha256}. {AVAILABILITY_BASIS} "
                "ECMWF 00 UTC atmospheric dissemination ends at 07:34 UTC in the "
                "schedule reviewed 2026-09-23; +10h includes a 2h26m buffer. "
                f"Schedule: {ECMWF_SCHEDULE_URL}; open data: {ECMWF_OPEN_DATA_URL}. "
                "The current schedule does not establish historical release times. "
                "Open-Meteo describes the early archive as IFS Cycle 49R1 hindcasts; "
                "contemporaneous operational availability is not proven. "
                f"Source documentation: {OPEN_METEO_SINGLE_RUNS_URL}. "
                "retrieved_at is the local import time, not original API retrieval."
            )
        snapshots.append(
            WeatherSnapshot(
                id=f"ecmwf00-{protocol_token}-{mode}-{source_sha256[:12]}-{loc}-{run_init:%Y%m%d}",
                turbine_id=f"turbine-{loc}",
                source="open-meteo-single-run",
                weather_model="ecmwf_ifs",
                run_init=run_init,
                retrieved_at=imported_at,
                available_at=(
                    run_init + timedelta(hours=ECMWF_PUBLICATION_DELAY_HOURS)
                    if accept_schedule_assumption
                    else None
                ),
                verification="verified" if accept_schedule_assumption else "unverified",
                availability_evidence=evidence,
                wind_height_m=100,
                points=sorted(points, key=lambda point: point.valid_time),
            )
        )
    dates = sorted({run.date() for run, _ in groups})
    missing_dates = []
    if dates:
        cursor, last = dates[0], dates[-1]
        present = set(dates)
        while cursor <= last:
            if cursor not in present:
                missing_dates.append(cursor.isoformat())
            cursor += timedelta(days=1)
    metadata = {
        "protocol": ECMWF_IMPORT_PROTOCOL,
        "source": "Open-Meteo Single Runs",
        "model": "ecmwf_ifs",
        "source_file": path.name,
        "source_sha256": source_sha256,
        "run_hour_utc": ECMWF_RUN_HOUR_UTC,
        "issue_hour_utc": ECMWF_ISSUE_HOUR_UTC,
        "publication_delay_hours": ECMWF_PUBLICATION_DELAY_HOURS,
        "availability_basis": AVAILABILITY_BASIS,
        "schedule_assumption_accepted": accept_schedule_assumption,
        "historical_operational_availability_proven": False,
        "hindcast": True,
        "documentation_reviewed_on": DOCUMENTATION_REVIEWED_ON,
        "sources": [OPEN_METEO_SINGLE_RUNS_URL, ECMWF_SCHEDULE_URL, ECMWF_OPEN_DATA_URL],
        "limitations": list(ARCHIVE_LIMITATIONS),
        "wind_height_m": 100,
        "units": {"wind_speed": "m/s", "wind_direction": "degrees", "temperature": "C"},
        "units_evidence": (
            "windagent/openmeteo.py fetch_single_run explicitly requests "
            "wind_speed_unit=ms and timezone=GMT; temperature default is Celsius. "
            "Individual hourly_units responses are not retained in the compiled CSV."
        ),
        "timestamp_semantics": (
            "UTC source valid_time is unchanged; instantaneous weather at the hourly "
            "interval end is the feature for power averaged over the preceding hour."
        ),
        "counts": {
            "selected_rows": selected_rows,
            "excluded_other_cycle_rows": other_cycle_rows,
            "missing_required_weather_rows": missing_rows,
            "selected_run_location_groups": len(groups),
            "empty_groups_skipped": sum(not points for points in groups.values()),
            "snapshots": len(snapshots),
            "points": sum(len(snapshot.points) for snapshot in snapshots),
        },
        "missing_run_dates": missing_dates,
        "empty_groups": [
            {"run_init": run.isoformat(), "turbine_id": f"turbine-{loc}"}
            for (run, loc), points in sorted(groups.items())
            if not points
        ],
    }
    return ArchiveImport(snapshots=snapshots, metadata=metadata)


def load_ecmwf_snapshots(
    path: str | Path = DEFAULT_ARCHIVE_PATH,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    accept_schedule_assumption: bool = False,
    retrieved_at: datetime | None = None,
) -> list[WeatherSnapshot]:
    """Convenience wrapper when the caller does not need the import report."""
    return import_ecmwf_archive(
        path,
        start=start,
        end=end,
        accept_schedule_assumption=accept_schedule_assumption,
        retrieved_at=retrieved_at,
    ).snapshots
