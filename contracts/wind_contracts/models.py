from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


def utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def whole_hour(value: datetime) -> datetime:
    if value.minute or value.second or value.microsecond:
        raise ValueError("Timestamp must be aligned to a UTC hour")
    return value


Timestamp = Annotated[AwareDatetime, AfterValidator(utc)]
Hour = Annotated[Timestamp, AfterValidator(whole_hour)]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")]
Power = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Turbine(Contract):
    id: Identifier
    name: str
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    hub_height_m: float | None = Field(default=None, gt=0)
    rated_power_kw: float | None = Field(default=None, gt=0)
    maps_url: str | None = None

    @model_validator(mode="after")
    def paired_coordinates(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Set both latitude and longitude, or neither")
        return self


class Observation(Contract):
    turbine_id: Identifier
    valid_time: Hour
    available_at: Timestamp
    wind_speed_ms: float = Field(ge=0, le=100)
    temperature_c: float = Field(ge=-100, le=70)
    power_normalized: Power

    @model_validator(mode="after")
    def availability(self):
        if self.available_at < self.valid_time:
            raise ValueError("An observation cannot be available before its valid time")
        return self


class DatasetUpload(Contract):
    name: str = Field(min_length=1, max_length=120)
    is_demo: bool = False
    observations: list[Observation] = Field(min_length=1, max_length=100_000)

    @model_validator(mode="after")
    def unique_rows(self):
        keys = [(row.turbine_id, row.valid_time) for row in self.observations]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate turbine/time observations")
        return self


class DatasetInfo(Contract):
    id: Identifier
    name: str
    is_demo: bool = False
    rows: int
    first_time: Timestamp
    last_time: Timestamp


class TrainRequest(Contract):
    dataset_id: Identifier
    trained_through: Hour
    algorithm: Literal["binned-power-curve", "persistence", "catboost"] = "binned-power-curve"
    feature_set: Literal["scada", "weather-scada"] = "scada"
    first_origin: Hour | None = None
    last_origin: Hour | None = None
    horizon_hours: Literal[24, 48] = 48
    weather_source: Literal["archive", "demo"] = "archive"
    iterations: int = Field(default=300, ge=10, le=1000)
    depth: int = Field(default=6, ge=2, le=8)
    learning_rate: float = Field(default=0.05, gt=0, le=1)
    random_seed: int = Field(default=42, ge=0, le=2**31 - 1)

    @model_validator(mode="after")
    def training_window(self):
        if self.algorithm == "catboost":
            if self.first_origin is None or self.last_origin is None:
                raise ValueError(
                    "CatBoost requires first_origin and last_origin for daily forecast samples"
                )
            days = (self.last_origin - self.first_origin).total_seconds() / 86400
            if not 0 <= days <= 1096 or not days.is_integer():
                raise ValueError("Training origins must span 0..1096 whole days")
            if self.last_origin + timedelta(hours=self.horizon_hours) > self.trained_through:
                raise ValueError("Every training target must be at or before trained_through")
        elif self.first_origin is not None or self.last_origin is not None:
            raise ValueError("Forecast training origins apply only to CatBoost")
        return self


class ModelInfo(Contract):
    id: Identifier
    algorithm: str
    trained_through: Timestamp | None = None
    dataset_id: str | None = None
    training_rows: int = 0
    turbine_ids: list[str] = Field(default_factory=list)
    is_demo: bool = False


class WeatherPoint(Contract):
    valid_time: Hour
    wind_speed_ms: float = Field(ge=0, le=100)
    wind_direction_deg: float = Field(ge=0, le=360)
    temperature_c: float = Field(ge=-100, le=70)


class WeatherSnapshot(Contract):
    id: Identifier
    turbine_id: Identifier
    source: Literal["demo", "open-meteo-single-run", "external-archive"]
    weather_model: str
    run_init: Hour
    retrieved_at: Timestamp
    available_at: Timestamp | None = None
    verification: Literal["synthetic", "unverified", "verified"]
    availability_evidence: str | None = None
    wind_height_m: float = Field(gt=0)
    points: list[WeatherPoint] = Field(min_length=1, max_length=400)

    @model_validator(mode="after")
    def provenance(self):
        if self.available_at is not None and self.available_at < self.run_init:
            raise ValueError("available_at must be at or after run_init")
        if self.verification == "verified":
            if self.source == "demo" or self.available_at is None:
                raise ValueError("Verified archives need a real source and publication time")
            if not self.availability_evidence or not self.availability_evidence.strip():
                raise ValueError("Verified archives require availability evidence")
        if (self.source == "demo") != (self.verification == "synthetic"):
            raise ValueError("Only demo snapshots may be marked synthetic")
        times = [point.valid_time for point in self.points]
        if times != sorted(set(times)):
            raise ValueError("Weather hours must be unique and sorted")
        if times[0] < self.run_init:
            raise ValueError("Weather valid time cannot precede run initialization")
        return self


class WeatherFetchRequest(Contract):
    turbine_id: Identifier
    run_init: Hour
    weather_model: Literal["ecmwf_ifs"] = "ecmwf_ifs"


class ForecastRequest(Contract):
    turbine_ids: list[Identifier] = Field(min_length=1, max_length=20)
    issued_at: Hour
    horizon_hours: Literal[24, 48] = 48
    weather_source: Literal["demo", "archive"] = "demo"
    model_id: Identifier = "demo-power-curve"

    @model_validator(mode="after")
    def unique_turbines(self):
        if len(self.turbine_ids) != len(set(self.turbine_ids)):
            raise ValueError("Turbine IDs must be unique")
        return self


class ForecastPoint(Contract):
    turbine_id: Identifier
    valid_time: Hour
    lead_hours: int = Field(ge=1, le=48)
    power_normalized: Power


class AgentEvent(Contract):
    at: Timestamp
    stage: Literal["validate", "weather", "retry", "predict", "analyse", "complete", "failed"]
    message: str


class ForecastResult(Contract):
    model_id: Identifier
    input_fingerprint: str
    is_demo: bool
    snapshots: list[WeatherSnapshot]
    points: list[ForecastPoint]
    warnings: list[str]


class ForecastRun(Contract):
    id: Identifier
    created_at: Timestamp
    status: Literal["queued", "running", "succeeded", "failed"]
    request: ForecastRequest
    events: list[AgentEvent] = Field(default_factory=list)
    result: ForecastResult | None = None
    error: str | None = None


class RefreshResponse(Contract):
    changed: bool
    run: ForecastRun


class BacktestRequest(ForecastRequest):
    last_issued_at: Hour
    evaluation_start: Hour
    evaluation_end: Hour
    actuals_dataset_id: Identifier | None = None

    @model_validator(mode="after")
    def replay_window(self):
        days = (self.last_issued_at - self.issued_at).total_seconds() / 86400
        if days < 0 or days > 31 or not days.is_integer():
            raise ValueError("Replay must span 0–31 whole days, with one issue per day")
        if self.evaluation_start >= self.evaluation_end:
            raise ValueError("Evaluation end must be after start (exclusive)")
        return self


class Metric(Contract):
    turbine_id: str
    horizon: Literal["1-24", "25-48"]
    samples: int
    mae: float
    rmse: float


class BacktestRun(Contract):
    id: Identifier
    created_at: Timestamp
    is_demo: bool = False
    status: Literal["queued", "running", "succeeded", "failed"]
    request: BacktestRequest
    forecast_ids: list[str] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)
    scored_points: int = 0
    unscored_points: int = 0
    error: str | None = None


class ApiError(Contract):
    code: str
    message: str


class Health(Contract):
    status: Literal["ok"] = "ok"
    version: str = "0.1.0"
