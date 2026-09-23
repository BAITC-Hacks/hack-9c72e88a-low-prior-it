"""Deterministic temporal guards, independent of weather vendors and model code."""

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from pydantic import TypeAdapter
from wind_contracts.models import Hour, Timestamp


class TimedObservation(Protocol):
    turbine_id: str
    valid_time: datetime
    available_at: datetime


def forecast_lead(forecast_origin: datetime, target_time: datetime) -> int:
    origin = TypeAdapter(Hour).validate_python(forecast_origin)
    target = TypeAdapter(Hour).validate_python(target_time)
    lead = int((target - origin).total_seconds() / 3600)
    if not 1 <= lead <= 48:
        raise ValueError("Target must be 1..48 hours after forecast_origin")
    return lead


def validate_weather_timing(
    *,
    forecast_origin: datetime,
    target_time: datetime,
    weather_issue_time: datetime,
    available_at: datetime,
) -> int:
    """Initialization alone is insufficient: publication must also precede origin.

    Snapshot provenance/verification is separately enforced by ForecastAgent.
    """
    lead = forecast_lead(forecast_origin, target_time)
    origin = TypeAdapter(Hour).validate_python(forecast_origin)
    issue = TypeAdapter(Timestamp).validate_python(weather_issue_time)
    available = TypeAdapter(Timestamp).validate_python(available_at)
    if not issue <= available <= origin:
        raise ValueError("Weather issue and publication must be at or before forecast_origin")
    return lead


def observations_as_of[T: TimedObservation](
    rows: Iterable[T],
    *,
    turbine_id: str,
    forecast_origin: datetime,
) -> list[T]:
    """Filter BEFORE aggregation/rolling operations; never use target-relative lags."""
    origin = TypeAdapter(Timestamp).validate_python(forecast_origin)
    return sorted(
        (
            row
            for row in rows
            if row.turbine_id == turbine_id
            and row.valid_time <= origin
            and row.available_at <= origin
        ),
        key=lambda row: row.valid_time,
    )


def validate_chronological_split(
    training: Iterable[TimedObservation],
    validation: Iterable[TimedObservation],
    *,
    trained_through: datetime,
    validation_origin: datetime,
) -> None:
    """Check target and reporting cutoffs; feature lineage must be checked separately."""
    cutoff = TypeAdapter(Timestamp).validate_python(trained_through)
    origin = TypeAdapter(Hour).validate_python(validation_origin)
    train, valid = list(training), list(validation)
    if not train or not valid:
        raise ValueError("Training and validation must both contain observations")
    if cutoff > origin:
        raise ValueError("Training cutoff is after validation origin")
    if any(row.valid_time > cutoff or row.available_at > cutoff for row in train):
        raise ValueError("Training observations were not available by the cutoff")
    if any(row.valid_time <= origin for row in valid):
        raise ValueError("Validation targets must follow the validation origin")
