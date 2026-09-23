"""One feature builder for historical training and inference. No observed future weather."""

import math
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean, pstdev

from pydantic import TypeAdapter
from wind_agent.temporal import forecast_lead
from wind_contracts.models import Hour, Observation, WeatherPoint

FEATURE_VERSION = "weather-scada-v1"
FEATURE_NAMES = [
    "wind_speed_ms",
    "wind_direction_sin",
    "wind_direction_cos",
    "temperature_c",
    "hour_sin",
    "hour_cos",
    "day_sin",
    "day_cos",
    "lead_hours",
    "last_power",
    "last_wind",
    "last_temperature",
    "observation_age_hours",
] + [
    f"{field}_{stat}_{hours}h"
    for hours in (3, 6, 24)
    for field in ("power", "wind", "temperature")
    for stat in ("mean", "std", "count")
]
SCADA_FEATURE_NAMES = FEATURE_NAMES[4:]
LAG_HOURS = (1, 2, 3, 6, 12, 24, 48, 72, 168)
EXTENDED_FEATURE_VERSION = "scada-extended-v1"
EXTENDED_FEATURE_NAMES = (
    SCADA_FEATURE_NAMES
    + [f"{field}_lag_{lag}h" for lag in LAG_HOURS for field in ("power", "wind", "temperature")]
    + [
        f"{field}_{stat}_{hours}h"
        for hours in (48, 168)
        for field in ("power", "wind", "temperature")
        for stat in ("mean", "std", "min", "max", "count")
    ]
    + [f"{field}_change_{lag}h" for lag in (3, 24) for field in ("power", "wind", "temperature")]
)


def feature_schema(feature_set: str):
    if feature_set == "scada-extended":
        return EXTENDED_FEATURE_VERSION, EXTENDED_FEATURE_NAMES
    if feature_set == "scada":
        return FEATURE_VERSION, SCADA_FEATURE_NAMES
    if feature_set == "weather-scada":
        return FEATURE_VERSION, FEATURE_NAMES
    raise ValueError(f"Unsupported feature set: {feature_set}")


class ObservationHistory:
    """Immutable, indexed source data. All selection checks event AND availability time."""

    def __init__(self, rows: list[Observation]):
        self.rows = sorted(
            (Observation.model_validate(row.model_dump()) for row in rows),
            key=lambda row: (row.turbine_id, row.valid_time),
        )
        self.by_turbine = defaultdict(list)
        seen = set()
        for row in self.rows:
            key = row.turbine_id, row.valid_time
            if key in seen:
                raise ValueError("Duplicate turbine/time observations")
            seen.add(key)
            self.by_turbine[row.turbine_id].append(row)
        self.times = {t: [r.valid_time for r in rows] for t, rows in self.by_turbine.items()}

    def available(self, turbine_id: str, origin: datetime) -> list[Observation]:
        origin = TypeAdapter(Hour).validate_python(origin)
        rows = self.by_turbine.get(turbine_id, [])
        end = bisect_right(self.times.get(turbine_id, []), origin)
        return [row for row in rows[:end] if row.available_at <= origin]

    def scada_features(self, turbine_id: str, origin: datetime) -> list[float]:
        available = self.available(turbine_id, origin)
        if not available:
            raise ValueError(f"{turbine_id}: no SCADA available at {origin.isoformat()}")
        last = available[-1]
        result = [
            last.power_normalized,
            last.wind_speed_ms,
            last.temperature_c,
            (origin - last.valid_time).total_seconds() / 3600,
        ]
        for hours in (3, 6, 24):
            # Unique whole-hour observations: at most `hours` rows can fall in this window.
            window = [
                row
                for row in available[-hours:]
                if row.valid_time > origin - timedelta(hours=hours)
            ]
            for field in ("power_normalized", "wind_speed_ms", "temperature_c"):
                values = [getattr(row, field) for row in window]
                # Empty window != zero generation; CatBoost explicitly supports missing numeric values.
                result.extend(
                    [
                        mean(values) if values else math.nan,
                        pstdev(values) if values else math.nan,
                        len(values),
                    ]
                )
        return result

    def extended_features(self, turbine_id: str, origin: datetime) -> list[float]:
        available = self.available(turbine_id, origin)
        if not available:
            raise ValueError(f"{turbine_id}: no SCADA available at {origin.isoformat()}")
        fields = ("power_normalized", "wind_speed_ms", "temperature_c")
        # Exact origin-relative lag, never a row shift that crosses a missing hour.
        lookup = {row.valid_time: row for row in available[-169:]}
        result = []
        for lag in LAG_HOURS:
            row = lookup.get(origin - timedelta(hours=lag))
            result.extend(getattr(row, field) if row is not None else math.nan for field in fields)
        for hours in (48, 168):
            window = [
                row
                for row in available[-hours:]
                if row.valid_time > origin - timedelta(hours=hours)
            ]
            for field in fields:
                values = [getattr(row, field) for row in window]
                result.extend(
                    [mean(values), pstdev(values), min(values), max(values), len(values)]
                    if values
                    else [math.nan, math.nan, math.nan, math.nan, 0]
                )
        for lag in (3, 24):
            earlier = lookup.get(origin - timedelta(hours=lag))
            result.extend(
                getattr(available[-1], field) - getattr(earlier, field)
                if earlier is not None
                else math.nan
                for field in fields
            )
        return result


def build_scada_features(
    history: ObservationHistory,
    turbine_id: str,
    targets: list[datetime],
    origin: datetime,
    *,
    extended: bool = False,
) -> list[list[float]]:
    origin = TypeAdapter(Hour).validate_python(origin)
    if not targets or targets != sorted(set(targets)):
        raise ValueError("Targets must be nonempty, unique and sorted")
    scada = history.scada_features(turbine_id, origin)
    if extended:
        scada += history.extended_features(turbine_id, origin)
    result = []
    for target in targets:
        lead = forecast_lead(origin, target)
        hour = 2 * math.pi * target.hour / 24
        day = 2 * math.pi * (target.timetuple().tm_yday - 1) / 365.25
        result.append([math.sin(hour), math.cos(hour), math.sin(day), math.cos(day), lead, *scada])
    return result


def build_features(
    history: ObservationHistory,
    turbine_id: str,
    weather: list[WeatherPoint],
    origin: datetime,
) -> list[list[float]]:
    origin = TypeAdapter(Hour).validate_python(origin)
    times = [row.valid_time for row in weather]
    if not times or times != sorted(set(times)):
        raise ValueError("Weather targets must be nonempty, unique and sorted")
    base = build_scada_features(history, turbine_id, times, origin)
    result = []
    for row, features in zip(weather, base, strict=True):
        direction = math.radians(row.wind_direction_deg)
        result.append(
            [
                row.wind_speed_ms,
                math.sin(direction),
                math.cos(direction),
                row.temperature_c,
                *features,
            ]
        )
    return result
