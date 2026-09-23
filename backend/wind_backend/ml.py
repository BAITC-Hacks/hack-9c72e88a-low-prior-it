"""Replace/extend these baselines behind the Predictor protocol; keep HTTP out of ML."""

from collections import defaultdict
from datetime import datetime
from statistics import mean

from pydantic import TypeAdapter
from wind_agent.temporal import forecast_lead
from wind_contracts.models import ForecastPoint, Hour, ModelInfo, Observation, Turbine, WeatherPoint

from wind_backend.features import ObservationHistory


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
    def fit(
        cls,
        identifier: str,
        dataset_id: str,
        rows: list[Observation],
        cutoff: datetime,
        is_demo: bool = False,
    ):
        cutoff = TypeAdapter(Hour).validate_python(cutoff)
        rows = ObservationHistory(rows).rows
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
            is_demo=is_demo,
        )
        return cls(info, curves)

    def predict(
        self, turbine: Turbine, weather: list[WeatherPoint], issued_at: datetime
    ) -> list[ForecastPoint]:
        validate_model_origin(self.info, issued_at)
        if turbine.id not in self.curves:
            raise ValueError(f"Model was not trained for {turbine.id}")
        curve = self.curves[turbine.id]

        def power(speed: float) -> float:
            nearest = min(curve, key=lambda key: (abs(int(key) + 0.5 - speed), int(key)))
            return curve[nearest]

        return forecast_points(turbine.id, weather, issued_at, power)


def validate_model_origin(info: ModelInfo, issued_at: datetime) -> datetime:
    origin = TypeAdapter(Hour).validate_python(issued_at)
    if info.trained_through is not None and info.trained_through > origin:
        raise ValueError("Model training cutoff is later than the forecast issue time")
    return origin


class PersistencePredictor:
    """Use the latest observation available at origin; never a target-relative lag."""

    def __init__(self, info: ModelInfo, rows: list[Observation]):
        self.info = info
        self.history = ObservationHistory(rows)

    @classmethod
    def fit(cls, identifier, dataset_id, rows, cutoff, is_demo=False):
        cutoff = TypeAdapter(Hour).validate_python(cutoff)
        usable = [
            r
            for r in ObservationHistory(rows).rows
            if r.valid_time <= cutoff and r.available_at <= cutoff
        ]
        if not usable:
            raise ValueError("No observations were available by the training cutoff")
        return cls(
            ModelInfo(
                id=identifier,
                algorithm="persistence-v1",
                trained_through=cutoff,
                dataset_id=dataset_id,
                training_rows=len(usable),
                turbine_ids=sorted({r.turbine_id for r in usable}),
                is_demo=is_demo,
            ),
            rows,
        )

    def predict_targets(self, turbine: Turbine, targets: list[datetime], issued_at: datetime):
        origin = validate_model_origin(self.info, issued_at)
        available = self.history.available(turbine.id, origin)
        if not available:
            raise ValueError(f"{turbine.id}: no observations available at forecast origin")
        if not targets or targets != sorted(set(targets)):
            raise ValueError("Targets must be nonempty, unique and sorted")
        return [
            ForecastPoint(
                turbine_id=turbine.id,
                valid_time=target,
                lead_hours=forecast_lead(origin, target),
                power_normalized=available[-1].power_normalized,
            )
            for target in targets
        ]

    def predict(self, turbine, weather, issued_at):
        return self.predict_targets(turbine, [r.valid_time for r in weather], issued_at)


def forecast_points(turbine_id, weather, issued_at, power):
    times = [r.valid_time for r in weather]
    if not times or times != sorted(set(times)):
        raise ValueError("Weather targets must be nonempty, unique and sorted")
    return [
        ForecastPoint(
            turbine_id=turbine_id,
            valid_time=row.valid_time,
            lead_hours=forecast_lead(issued_at, row.valid_time),
            power_normalized=round(power(row.wind_speed_ms), 6),
        )
        for row in weather
    ]
