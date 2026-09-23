from datetime import datetime
from typing import Protocol

from wind_contracts.models import (
    ForecastPoint,
    ForecastRequest,
    ModelInfo,
    Turbine,
    WeatherPoint,
    WeatherSnapshot,
)


class Predictor(Protocol):
    info: ModelInfo

    def predict(
        self, turbine: Turbine, weather: list[WeatherPoint], issued_at: datetime
    ) -> list[ForecastPoint]: ...


class WeatherProvider(Protocol):
    async def fetch(self, turbine: Turbine, request: ForecastRequest) -> WeatherSnapshot: ...


class WeatherUnavailable(ValueError):
    """No permissible inputs exist. Never fall back to future or observed weather."""


class TransientWeatherError(RuntimeError):
    """Retryable transport/provider failure."""
