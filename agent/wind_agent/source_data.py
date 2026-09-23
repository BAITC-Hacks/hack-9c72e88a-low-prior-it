"""Explicit adapter for organizer CSVs; original files remain untouched."""

import csv
import hashlib
import re
from collections import Counter
from datetime import UTC, datetime, timedelta, tzinfo
from datetime import timezone as fixed_timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from wind_contracts.scada import ScadaReading

SOURCE_COLUMNS = {
    "valid_time": "Статистическое время",
    "wind_speed_ms": "Средняя скорость ветра(m/s)",
    "power_normalized": "Нормализованная активная мощность",
    "temperature_c": "Средняя температура окружающей среды(°C)",
}


def source_timezone(name: str) -> tzinfo:
    """Accept IANA zones or explicit UTC offsets without applying civil-time changes."""
    if name == "UTC":
        return UTC
    if name.startswith("UTC"):
        match = re.fullmatch(r"UTC([+-])(\d{2}):(\d{2})", name)
        if match is None:
            raise ValueError("Fixed timezone must use UTC+HH:MM or UTC-HH:MM")
        sign, hours, minutes = match.groups()
        if int(hours) > 23 or int(minutes) > 59:
            raise ValueError("Invalid fixed UTC offset")
        offset = timedelta(hours=int(hours), minutes=int(minutes))
        return fixed_timezone(offset if sign == "+" else -offset)
    return ZoneInfo(name)


def local_to_utc(moment: datetime, zone: tzinfo) -> datetime:
    """Reject ambiguous/nonexistent civil times instead of guessing a DST fold."""
    candidates = set()
    for fold in (0, 1):
        aware = moment.replace(tzinfo=zone, fold=fold)
        utc = aware.astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) == moment:
            candidates.add(utc)
    if len(candidates) != 1:
        raise ValueError("Ambiguous or nonexistent local timestamp")
    return candidates.pop()


def read_organizer_csv(
    path: str | Path,
    *,
    turbine_id: str,
    timezone: str,
    timestamp_position: str,
    latency_minutes: int,
    quarantine_invalid: bool = False,
):
    if timestamp_position not in {"start", "end"} or latency_minutes < 0:
        raise ValueError("Specify timestamp_position=start/end and nonnegative latency_minutes")
    path = Path(path)
    zone = source_timezone(timezone)
    rows, issues, seen = [], [], set()
    source_count = 0
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not set(SOURCE_COLUMNS.values()) <= set(reader.fieldnames or []):
            raise ValueError(f"{path.name}: missing organizer CSV columns")
        for record in reader:
            source_count += 1
            try:
                moment = datetime.strptime(
                    record[SOURCE_COLUMNS["valid_time"]], "%Y-%m-%d %H:%M:%S"
                )
                valid = local_to_utc(moment, zone)
                if timestamp_position == "start":
                    valid += timedelta(minutes=10)
                if valid in seen:
                    raise ValueError("Duplicate turbine/time reading")
                row = ScadaReading(
                    turbine_id=turbine_id,
                    valid_time=valid,
                    available_at=valid + timedelta(minutes=latency_minutes),
                    **{
                        field: record[column]
                        for field, column in SOURCE_COLUMNS.items()
                        if field != "valid_time"
                    },
                )
                seen.add(valid)
                rows.append(row)
            except (ValueError, TypeError) as exc:
                issues.append({"line": reader.line_num, "reason": str(exc)})
    if issues and not quarantine_invalid:
        raise ValueError(f"{len(issues)} invalid source rows; first: {issues[0]}")
    if not rows:
        raise ValueError("Source contains no usable readings")
    return rows, {
        "source": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "turbine_id": turbine_id,
        "source_rows": source_count,
        "accepted_rows": len(rows),
        "quarantined_rows": len(issues),
        "quarantine_reasons": dict(Counter(i["reason"] for i in issues)),
        "issues": issues,
    }
