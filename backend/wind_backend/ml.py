"""Replace/extend these baselines behind the Predictor protocol; keep HTTP out of ML."""

from collections import defaultdict
from datetime import datetime
from statistics import mean

from wind_contracts.models import ForecastPoint, ModelInfo, Observation, Turbine, WeatherPoint


class DemoPowerCurve:
    info = ModelInfo(id="demo-power-curve", algorithm="illustrative-cubic-curve", is_demo=True)

    def predict(
        self, turbine: Turbine, weather: list[WeatherPoint], issued_at: datetime
    ) -> list[ForecastPoint]:
        def power(speed: float) -> float:
            if speed < 3 or speed >= 25:
                return 0.0
            return min(1.0, (speed**3 - 3**3) / (12**3 - 3**3))

        return forecast_points(turbine.id, weather, issued_at, power)


class BinnedPowerCurve:
    """Empirical baseline trained on measured wind; forecast-weather bias is not corrected yet."""

    def __init__(self, info: ModelInfo, curves: dict[str, dict[str, float]]):
        self.info = info
        self.curves = curves

    @classmethod
    def fit(cls, identifier: str, dataset_id: str, rows: list[Observation], cutoff: datetime):
        usable = [r for r in rows if r.valid_time <= cutoff and r.available_at <= cutoff]
        if not usable:
            raise ValueError("No observations were available by the training cutoff")
        bins = defaultdict(lambda: defaultdict(list))
        for row in usable:
            bins[row.turbine_id][str(int(row.wind_speed_ms))].append(row.power_normalized)
        curves = {
            turbine: {speed: mean(values) for speed, values in groups.items()}
            for turbine, groups in bins.items()
        }
        info = ModelInfo(
            id=identifier,
            algorithm="binned-power-curve-v1",
            trained_through=cutoff,
            dataset_id=dataset_id,
            training_rows=len(usable),
            turbine_ids=sorted(curves),
        )
        return cls(info, curves)

    def predict(
        self, turbine: Turbine, weather: list[WeatherPoint], issued_at: datetime
    ) -> list[ForecastPoint]:
        if turbine.id not in self.curves:
            raise ValueError(f"Model was not trained for {turbine.id}")
        curve = self.curves[turbine.id]

        def power(speed: float) -> float:
            nearest = min(curve, key=lambda key: (abs(int(key) + 0.5 - speed), int(key)))
            return curve[nearest]

        return forecast_points(turbine.id, weather, issued_at, power)


def forecast_points(turbine_id, weather, issued_at, power):
    return [
        ForecastPoint(
            turbine_id=turbine_id,
            valid_time=row.valid_time,
            lead_hours=int((row.valid_time - issued_at).total_seconds() // 3600),
            power_normalized=round(power(row.wind_speed_ms), 6),
        )
        for row in weather
    ]
