from datetime import datetime
from typing import Callable, Protocol

from wind_contracts import Event, ForecastPoint, ForecastRequest, ModelInfo, Turbine, WeatherSnapshot

Emit = Callable[[Event], None]


class ForecastError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.status = code, status


class WeatherProvider(Protocol):
    def get(self, request: ForecastRequest, turbine: Turbine, emit: Emit) -> WeatherSnapshot: ...


class Predictor(Protocol):
    info: ModelInfo

    def predict(self, turbine: Turbine, weather: WeatherSnapshot,
                issued_at: datetime) -> list[ForecastPoint]: ...
