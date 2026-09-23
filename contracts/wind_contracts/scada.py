"""Internal preprocessing contracts; public HTTP schemas remain unchanged."""

from pydantic import Field, model_validator

from wind_contracts.models import Contract, Hour, Identifier, Observation, Power, Timestamp


class ScadaReading(Contract):
    """One interval-end reading with an explicit observation availability time."""

    turbine_id: Identifier
    valid_time: Timestamp
    available_at: Timestamp
    wind_speed_ms: float = Field(ge=0, le=100)
    temperature_c: float = Field(ge=-100, le=70)
    power_normalized: Power

    @model_validator(mode="after")
    def availability(self):
        if self.available_at < self.valid_time:
            raise ValueError("An observation cannot be available before its valid time")
        return self


class HourlyScada(Contract):
    """Statistics for (valid_time - 1h, valid_time], using population stddev."""

    turbine_id: Identifier
    valid_time: Hour
    available_at: Timestamp
    sample_count: int = Field(ge=1)
    expected_count: int = Field(ge=1)
    wind_mean: float = Field(ge=0, le=100)
    wind_std: float = Field(ge=0)
    wind_min: float = Field(ge=0, le=100)
    wind_max: float = Field(ge=0, le=100)
    power_mean: Power
    power_std: float = Field(ge=0)
    power_min: Power
    power_max: Power
    temperature_mean: float = Field(ge=-100, le=70)
    temperature_std: float = Field(ge=0)

    @model_validator(mode="after")
    def coverage_and_availability(self):
        if self.sample_count > self.expected_count:
            raise ValueError("sample_count cannot exceed expected_count")
        if self.available_at < self.valid_time:
            raise ValueError("An hourly aggregate cannot be available before its interval ends")
        return self

    @property
    def complete(self) -> bool:
        return self.sample_count == self.expected_count

    def to_observation(self) -> Observation:
        if not self.complete:
            raise ValueError("Incomplete hours cannot become training targets")
        return Observation(
            turbine_id=self.turbine_id,
            valid_time=self.valid_time,
            available_at=self.available_at,
            wind_speed_ms=self.wind_mean,
            temperature_c=self.temperature_mean,
            power_normalized=self.power_mean,
        )
