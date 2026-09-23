"""Strict SCADA ingestion and regular interval-end aggregation, with no imputation."""

import csv
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, pstdev

from pydantic import TypeAdapter, ValidationError
from wind_contracts.models import Timestamp
from wind_contracts.scada import HourlyScada, ScadaReading

from wind_agent.temporal import observations_as_of


@dataclass(frozen=True)
class CsvIssue:
    line: int
    message: str


@dataclass(frozen=True)
class ScadaCsvReport:
    rows: list[ScadaReading]
    issues: list[CsvIssue]
    source_rows: int


def inspect_scada_csv(
    path: str | Path,
    *,
    columns: Mapping[str, str] | None = None,
    delimiter: str = ",",
) -> ScadaCsvReport:
    """Map canonical names to source headers. Invalid rows are reported, never repaired.

    Use parse_scada_csv for ingestion: this inspection result may be incomplete.
    Naive timestamps, missing latency metadata, nonfinite and out-of-range values
    are errors. Extra source columns are ignored only with an explicit mapping.
    """
    fields = set(ScadaReading.model_fields)
    mapping = dict(columns) if columns is not None else {key: key for key in fields}
    if set(mapping) != fields or len(set(mapping.values())) != len(fields):
        raise ValueError("Column mapping must cover every canonical field exactly once")
    rows, issues, seen = [], [], set()
    count = 0
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, delimiter=delimiter)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or not set(mapping.values()) <= set(headers):
            raise ValueError("CSV has duplicate or missing required headers")
        if columns is None and set(headers) != fields:
            raise ValueError("Noncanonical CSV headers require an explicit column mapping")
        for row in reader:
            count += 1
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("CSV row width does not match headers")
                reading = ScadaReading.model_validate(
                    {key: row[name] for key, name in mapping.items()}
                )
                key = (reading.turbine_id, reading.valid_time)
                if key in seen:
                    raise ValueError("Duplicate turbine/time reading")
                seen.add(key)
                rows.append(reading)
            except (ValidationError, ValueError) as exc:
                issues.append(CsvIssue(reader.line_num, str(exc)))
    return ScadaCsvReport(rows, issues, count)


def parse_scada_csv(path: str | Path, **kwargs) -> list[ScadaReading]:
    report = inspect_scada_csv(path, **kwargs)
    if report.issues:
        first = report.issues[0]
        raise ValueError(
            f"{len(report.issues)} invalid SCADA rows; line {first.line}: {first.message}"
        )
    if not report.rows:
        raise ValueError("SCADA CSV contains no readings")
    return report.rows


def _regular_rows(rows: Iterable[ScadaReading], interval_minutes: int) -> list[ScadaReading]:
    if (
        isinstance(interval_minutes, bool)
        or not isinstance(interval_minutes, int)
        or interval_minutes <= 0
        or 60 % interval_minutes
    ):
        raise ValueError("interval_minutes must be a positive integer divisor of 60")
    result = sorted(rows, key=lambda row: (row.turbine_id, row.valid_time))
    seen = set()
    for row in result:
        key = row.turbine_id, row.valid_time
        if key in seen:
            raise ValueError("Duplicate turbine/time reading")
        seen.add(key)
        moment = row.valid_time
        if moment.minute % interval_minutes or moment.second or moment.microsecond:
            raise ValueError("Reading is not aligned to the configured UTC sampling interval")
    return result


def profile_scada(rows: Iterable[ScadaReading], *, interval_minutes: int = 10) -> dict:
    """Profile validated readings per turbine; missing slots exclude unknown outer edges."""
    groups = defaultdict(list)
    for row in _regular_rows(rows, interval_minutes):
        groups[row.turbine_id].append(row)
    result = {}
    for turbine, group in groups.items():
        expected = (
            int(
                (group[-1].valid_time - group[0].valid_time).total_seconds()
                / (interval_minutes * 60)
            )
            + 1
        )
        result[turbine] = {
            "rows": len(group),
            "first_time": group[0].valid_time,
            "last_time": group[-1].valid_time,
            "missing_slots": expected - len(group),
            "zero_power_rows": sum(row.power_normalized == 0 for row in group),
            "delayed_rows": sum(row.available_at > row.valid_time for row in group),
            "power_min": min(row.power_normalized for row in group),
            "power_max": max(row.power_normalized for row in group),
            "hour_coverage": dict(
                Counter(
                    row.sample_count
                    for row in aggregate_hourly(group, interval_minutes=interval_minutes)
                )
            ),
        }
    return result


def aggregate_hourly(
    rows: Iterable[ScadaReading],
    *,
    interval_minutes: int = 10,
    forecast_origin: datetime | None = None,
) -> list[HourlyScada]:
    """Aggregate (T-1h, T], preserving counts and latest input availability.

    Supplying an origin filters raw observations before computing statistics and
    excludes unfinished hours. Without an origin this is offline target preparation;
    callers must still filter aggregates by valid_time AND available_at for features.
    Missing hours are absent, partial hours are marked, and no values are filled.
    """
    readings = list(rows)
    origin = None
    if forecast_origin is not None:
        origin = TypeAdapter(Timestamp).validate_python(forecast_origin)
        readings = [
            row
            for turbine in sorted({r.turbine_id for r in readings})
            for row in observations_as_of(readings, turbine_id=turbine, forecast_origin=origin)
        ]
    groups = defaultdict(list)
    for row in _regular_rows(readings, interval_minutes):
        hour = row.valid_time.replace(minute=0, second=0, microsecond=0)
        if row.valid_time != hour:
            hour += timedelta(hours=1)
        if origin is None or hour <= origin:
            groups[row.turbine_id, hour].append(row)
    result = []
    for (turbine, hour), group in sorted(groups.items()):
        stats = {}
        for name, field in [
            ("wind", "wind_speed_ms"),
            ("power", "power_normalized"),
            ("temperature", "temperature_c"),
        ]:
            values = [getattr(row, field) for row in group]
            stats[f"{name}_mean"] = mean(values)
            stats[f"{name}_std"] = pstdev(values)
            if name != "temperature":
                stats[f"{name}_min"], stats[f"{name}_max"] = min(values), max(values)
        result.append(
            HourlyScada(
                turbine_id=turbine,
                valid_time=hour,
                available_at=max(hour, *(row.available_at for row in group)),
                sample_count=len(group),
                expected_count=60 // interval_minutes,
                **stats,
            )
        )
    return result
