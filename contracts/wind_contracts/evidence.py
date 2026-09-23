"""Read-only, reproducible model evidence, separate from live forecast results."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from wind_contracts.models import Contract, Hour, Metric, Timestamp

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Count = Annotated[int, Field(ge=0)]


class EvidenceScore(Contract):
    samples: int = Field(gt=0)
    mae: float = Field(ge=0, le=1)
    rmse: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def consistent_errors(self):
        if self.rmse + 1e-12 < self.mae:
            raise ValueError("RMSE cannot be lower than MAE")
        return self


class EvidenceMetric(Metric):
    samples: int = Field(gt=0)
    mae: float = Field(ge=0, le=1)
    rmse: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def consistent_errors(self):
        if self.rmse + 1e-12 < self.mae:
            raise ValueError("RMSE cannot be lower than MAE")
        return self


class EvidenceModel(Contract):
    id: Literal[
        "selected", "previous", "constant", "climatology", "persistence", "scada", "weather_scada"
    ]
    label: str
    selected: bool = False
    scored_pairs_sha256: Sha256 | None = None
    pooled: EvidenceScore
    metrics: list[EvidenceMetric] = Field(min_length=1)


class EvidenceBenchmark(Contract):
    name: str
    first_issue: Hour
    last_issue: Hour
    issue_step_hours: Literal[24] = 24
    horizon_hours: Literal[48] = 48
    trained_through: Hour
    feature_set: str
    reused_comparison: Literal[True] = True
    scored_pairs: int = Field(gt=0)
    unscored_pairs: Count
    models: list[EvidenceModel] = Field(min_length=3, max_length=7)


class EvidenceFold(Contract):
    name: str
    first_issue: Hour
    last_issue: Hour
    pooled: EvidenceScore
    scored_pairs: int = Field(gt=0)
    unscored_pairs: Count


class EvidenceCandidate(Contract):
    name: str
    selected: bool
    feature_set: str
    iterations: int = Field(gt=0)
    depth: int = Field(gt=0)
    loss_function: Literal["MAE", "RMSE"]
    pooled: EvidenceScore
    folds: list[EvidenceFold] = Field(min_length=1)


class EvidenceSelection(Contract):
    objective: str
    first_training_origin: Hour
    candidates: list[EvidenceCandidate] = Field(min_length=1)


class EvidenceSource(Contract):
    turbine_id: str
    source_file: str
    sha256: Sha256
    rows: Count
    complete_hours: Count
    incomplete_hours: Count
    missing_slots: Count


class EvidenceData(Contract):
    complete_hours: Count
    timezone: str
    timestamp_position: str
    latency_minutes: Count
    provisional: Literal[True] = True
    history_sha256: Sha256
    sources: list[EvidenceSource] = Field(min_length=1)


class EvidenceRefit(Contract):
    trained_through: Hour
    training_rows: int = Field(gt=0)
    evaluated: Literal[False] = False


class EvidenceCheckpoint(Contract):
    id: str
    status: Literal["verified", "provisional", "open"]
    title: str
    detail: str


class EvidenceWeather(Contract):
    source: str
    model: str
    source_sha256: Sha256
    run_hour_utc: int = Field(ge=0, le=23)
    issue_hour_utc: int = Field(ge=0, le=23)
    publication_delay_hours: int = Field(ge=0, le=24)
    availability_basis: str = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)


class EvidenceReport(Contract):
    status: Literal["provisional"] = "provisional"
    source_file: str
    source_sha256: Sha256
    selected_at: Timestamp
    benchmark: EvidenceBenchmark
    selection: EvidenceSelection
    data: EvidenceData
    weather: EvidenceWeather | None = None
    refit: EvidenceRefit
    checkpoints: list[EvidenceCheckpoint]
    limitations: list[str]
