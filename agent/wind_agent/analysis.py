"""Descriptive forecast analysis; never changes predictions or implies confidence."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from statistics import mean

from wind_contracts.models import ForecastPoint


def _utc(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="minutes").replace("+00:00", "Z")


def summarize_forecast(points: Sequence[ForecastPoint], *, is_demo: bool) -> list[str]:
    """Return one deterministic message per turbine, with earliest-hour tie breaks.

    The agent calls this after validating the complete forecast. The helper also
    avoids bridging gaps when used with a partial series. Ramps compare adjacent
    hourly means, whose timestamps denote interval ends, not instantaneous power.
    """
    grouped = defaultdict(list)
    for point in points:
        grouped[point.turbine_id].append(point)

    messages = []
    for turbine_id, group in sorted(grouped.items()):
        rows = sorted(group, key=lambda point: point.valid_time)
        peak = max(rows, key=lambda point: point.power_normalized)
        qualifier = "DEMO / PROVISIONAL: " if is_demo else "Forecast analysis: "
        parts = [
            f"{qualifier}{turbine_id}; leads {rows[0].lead_hours}-{rows[-1].lead_hours} h; "
            f"{len(rows)} hourly means, interval ends {_utc(rows[0].valid_time)} "
            f"to {_utc(rows[-1].valid_time)} (UTC).",
            f"Mean {100 * mean(point.power_normalized for point in rows):.2f}% "
            f"of normalized power; peak {100 * peak.power_normalized:.2f}% "
            f"at lead {peak.lead_hours} h, interval ending {_utc(peak.valid_time)}.",
        ]
        adjacent = [
            (left, right, right.power_normalized - left.power_normalized)
            for left, right in pairwise(rows)
            if right.valid_time - left.valid_time == timedelta(hours=1)
        ]
        if not adjacent:
            parts.append("Hourly change unavailable: no adjacent hourly intervals.")
        elif all(change == 0 for _, _, change in adjacent):
            parts.append("Stable across adjacent hourly means: 0.00 percentage-point change.")
        else:
            for label, candidates, choose in (
                ("rise", [item for item in adjacent if item[2] > 0], max),
                ("drop", [item for item in adjacent if item[2] < 0], min),
            ):
                if not candidates:
                    parts.append(f"No hourly {label} in the forecast.")
                    continue
                # Remove insignificant arithmetic noise so equivalent changes
                # choose the earliest interval consistently.
                left, right, change = choose(candidates, key=lambda item: round(item[2], 12))
                parts.append(
                    f"Largest hourly {label} {100 * change:+.2f} percentage points: "
                    f"lead {left.lead_hours} to {right.lead_hours} h; interval ends "
                    f"{_utc(left.valid_time)} to {_utc(right.valid_time)}."
                )
        if len(adjacent) != len(rows) - 1:
            parts.append("Hourly changes exclude gaps; missing hours are not inferred.")
        messages.append(" ".join(parts))
    return messages
