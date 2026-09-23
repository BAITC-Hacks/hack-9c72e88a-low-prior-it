"""Shared, strict public contracts. Every timestamp is timezone-aware UTC."""
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator


def utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def hour(value: datetime) -> datetime:
    if value.minute or value.second or value.microsecond:
        raise ValueError("timestamp must be on an exact hour")
    return value


UTC = Annotated[AwareDatetime, AfterValidator(utc)]
Hour = Annotated[UTC, AfterValidator(hour)]
Identifier = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.-]+$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class APIError(Contract):
    code: str
    message: str


class Turbine(Contract):
    id: Identifier
    name: str
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    capacity_kw: float | None = Field(default=None, gt=0)
    hub_height_m: float | None = Field(default=None, gt=0)
    metadata_note: str = "Unconfirmed metadata"


class Observation(Contract):
    turbine_id: Identifier
    valid_time: Hour
    available_at: UTC
    wind_speed_ms: float = Field(ge=0, le=100)
    temperature_c: float = Field(ge=-90, le=70)
    power_normalized: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def latency(self):
        if self.available_at < self.valid_time:
            raise ValueError("observation cannot be available before its interval ends")
        return self


class DatasetImport(Contract):
    name: str = Field(min_length=1, max_length=200)
    demo: bool = False
    provenance: str = Field(min_length=1)
    observations: list[Observation] = Field(min_length=1, max_length=200000)

    @model_validator(mode="after")
    def unique_rows(self):
        keys = [(p.turbine_id, p.valid_time) for p in self.observations]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate turbine/valid_time observation")
        return self


class DatasetInfo(Contract):
    id: Identifier
    name: str
    demo: bool
    provenance: str
    row_count: int
    start: UTC
    end: UTC
    fingerprint: str


class WeatherPoint(Contract):
    valid_time: Hour
    wind_speed_ms: float = Field(ge=0, le=100)
    temperature_c: float = Field(ge=-90, le=70)
    wind_direction_deg: float = Field(ge=0, le=360)


class WeatherSnapshot(Contract):
    id: Identifier
    turbine_id: Identifier
    source: str = Field(min_length=1)
    weather_model: str
    kind: Literal["forecast", "hindcast", "reanalysis", "synthetic"] = "forecast"
    verification: Literal["unverified", "verified", "demo"] = "unverified"
    run_init: Hour
    available_at: UTC | None = None
    retrieved_at: UTC
    availability_evidence: str = ""
    wind_height_m: float = Field(gt=0)
    wind_unit: Literal["m/s"] = "m/s"
    temperature_unit: Literal["°C"] = "°C"
    direction_unit: Literal["degrees"] = "degrees"
    preparation: str = "No interpolation; incomplete horizons are rejected."
    points: list[WeatherPoint] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def lineage(self):
        times = [p.valid_time for p in self.points]
        if len(set(times)) != len(times):
            raise ValueError("duplicate weather timestamp")
        if min(times) < self.run_init:
            raise ValueError("weather valid time precedes model initialization")
        if self.available_at is not None and self.available_at < self.run_init:
            raise ValueError("publication precedes initialization")
        if self.verification == "verified":
            if self.kind != "forecast" or self.available_at is None or not self.availability_evidence.strip():
                raise ValueError("verified snapshots require original forecasts and publication evidence")
        if self.verification == "demo" and self.kind != "synthetic":
            raise ValueError("demo snapshots must be synthetic")
        return self


class WeatherFetch(Contract):
    turbine_id: Identifier
    run_init: Hour
    weather_model: Literal["ecmwf_ifs"] = "ecmwf_ifs"


class TrainRequest(Contract):
    dataset_id: Identifier
    trained_through: Hour
    algorithm: Literal["binned-curve", "persistence", "weather-ridge"] = "binned-curve"
    weather_snapshot_ids: list[Identifier] = Field(default_factory=list)


class ModelInfo(Contract):
    id: Identifier
    algorithm: str
    version: str = "1"
    demo: bool
    dataset_id: str | None = None
    trained_through: UTC | None = None
    training_rows: int = 0
    turbine_ids: list[str] = Field(default_factory=list)
    fingerprint: str
    warnings: list[str] = Field(default_factory=list)


class ForecastRequest(Contract):
    turbine_ids: list[Identifier] = Field(min_length=1, max_length=20)
    issued_at: Hour
    horizon_hours: Literal[24, 48] = 48
    weather_source: Literal["demo", "archive"] = "demo"
    model_id: Identifier = "demo-power-curve"

    @model_validator(mode="after")
    def unique_turbines(self):
        if len(set(self.turbine_ids)) != len(self.turbine_ids):
            raise ValueError("duplicate turbine ID")
        return self


class ForecastPoint(Contract):
    turbine_id: Identifier
    valid_time: Hour
    lead_hours: int = Field(ge=1, le=48)
    power_normalized: float = Field(ge=0, le=1)


class Event(Contract):
    at: UTC
    step: str
    message: str


class ForecastResult(Contract):
    points: list[ForecastPoint]
    weather: list[WeatherSnapshot]
    model: ModelInfo
    demo: bool
    fingerprint: str
    warnings: list[str]


Status = Literal["queued", "running", "succeeded", "failed"]


class ForecastRun(Contract):
    id: Identifier
    created_at: UTC
    request: ForecastRequest
    status: Status
    fingerprint: str
    result: ForecastResult | None = None
    events: list[Event] = Field(default_factory=list)
    error: APIError | None = None


class BacktestRequest(ForecastRequest):
    end_issue_at: Hour
    evaluation_start: Hour
    evaluation_end: Hour
    actual_dataset_id: Identifier | None = None

    @model_validator(mode="after")
    def windows(self):
        if self.end_issue_at < self.issued_at or (self.end_issue_at - self.issued_at).days > 366:
            raise ValueError("issue window must span 0..366 days")
        if (self.end_issue_at - self.issued_at).total_seconds() % 86400:
            raise ValueError("daily issues must use the same UTC hour")
        if self.evaluation_end <= self.evaluation_start:
            raise ValueError("evaluation window must be nonempty; end is exclusive")
        return self


class Metric(Contract):
    turbine_id: str
    horizon: Literal["1-24", "25-48"]
    predicted: int
    scored: int
    missing: int
    mae: float | None = None
    rmse: float | None = None


class BacktestRun(Contract):
    id: Identifier
    created_at: UTC
    request: BacktestRequest
    status: Status
    completed: int = 0
    total: int
    child_run_ids: list[str] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)
    demo: bool = False
    error: APIError | None = None
