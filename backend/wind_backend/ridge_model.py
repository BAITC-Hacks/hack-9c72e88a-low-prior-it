"""The danik branch's ridge candidate adapted to the shared Predictor contract."""

from datetime import timedelta

import numpy as np
from wind_agent.temporal import forecast_lead
from wind_contracts.models import ForecastPoint, ModelInfo, TrainRequest

from wind_backend.features import ObservationHistory
from wind_backend.ml import validate_model_origin


def features(point, issue, last_power):
    speed = point.wind_speed_ms
    angle = np.deg2rad(point.wind_direction_deg)
    phase = 2 * np.pi * point.valid_time.hour / 24
    return [
        speed,
        speed**2,
        speed**3,
        point.temperature_c,
        np.sin(angle),
        np.cos(angle),
        forecast_lead(issue, point.valid_time),
        np.sin(phase),
        np.cos(phase),
        last_power,
    ]


class WeatherRidge:
    def __init__(self, info, parameters, rows):
        self.info = info
        self.parameters = parameters
        self.history = ObservationHistory(rows)

    @classmethod
    def fit(cls, identifier, rows, request: TrainRequest, snapshots, is_demo=False):
        request = TrainRequest.model_validate(request.model_dump())
        history = ObservationHistory(rows)
        rows = [
            r
            for r in history.rows
            if r.valid_time <= request.trained_through and r.available_at <= request.trained_through
        ]
        if not rows:
            raise ValueError("No observations available by training cutoff")
        parameters, count = {}, 0
        for turbine in sorted({r.turbine_id for r in rows}):
            targets = {r.valid_time: r for r in rows if r.turbine_id == turbine}
            x, y, seen = [], [], set()
            for snapshot in sorted(snapshots, key=lambda s: (s.run_init, s.id), reverse=True):
                if (
                    snapshot.turbine_id != turbine
                    or snapshot.verification != "verified"
                    or snapshot.source == "demo"
                    or snapshot.available_at is None
                    or not snapshot.availability_evidence.strip()
                ):
                    continue
                issue = snapshot.available_at.replace(minute=0, second=0, microsecond=0)
                if issue < snapshot.available_at:
                    issue += timedelta(hours=1)
                if issue > request.trained_through or snapshot.run_init > issue:
                    continue
                available = history.available(turbine, issue)
                if not available:
                    continue
                for point in snapshot.points:
                    lead = (point.valid_time - issue).total_seconds() / 3600
                    key = (issue, point.valid_time)
                    if 1 <= lead <= 48 and point.valid_time in targets and key not in seen:
                        x.append(features(point, issue, available[-1].power_normalized))
                        y.append(targets[point.valid_time].power_normalized)
                        seen.add(key)
            if len(y) < 24:
                raise ValueError(
                    f"{turbine}: need at least 24 issue/valid pairs from verified forecasts"
                )
            x = np.array(x)
            mean, scale = x.mean(axis=0), x.std(axis=0)
            scale[scale < 1e-10] = 1
            design = np.column_stack([np.ones(len(x)), (x - mean) / scale])
            penalty = np.eye(design.shape[1]) * 10
            penalty[0, 0] = 0
            beta = np.linalg.solve(design.T @ design + penalty, design.T @ np.array(y))
            parameters[turbine] = {
                "mean": mean.tolist(),
                "scale": scale.tolist(),
                "beta": beta.tolist(),
            }
            count += len(y)
        info = ModelInfo(
            id=identifier,
            algorithm="weather-ridge-v1",
            dataset_id=request.dataset_id,
            trained_through=request.trained_through,
            training_rows=count,
            turbine_ids=sorted(parameters),
            is_demo=is_demo,
        )
        return cls(info, parameters, rows=history.rows)

    def predict(self, turbine, weather, issued_at):
        origin = validate_model_origin(self.info, issued_at)
        if turbine.id not in self.parameters:
            raise ValueError(f"Model was not trained for {turbine.id}")
        available = self.history.available(turbine.id, origin)
        if not available:
            raise ValueError(f"{turbine.id}: no observation available at issue time")
        params = self.parameters[turbine.id]
        points = []
        for point in weather:
            x = (
                np.array(features(point, origin, available[-1].power_normalized)) - params["mean"]
            ) / params["scale"]
            value = np.dot(np.r_[1, x], params["beta"])
            points.append(
                ForecastPoint(
                    turbine_id=turbine.id,
                    valid_time=point.valid_time,
                    lead_hours=forecast_lead(origin, point.valid_time),
                    power_normalized=float(np.clip(value, 0, 1)),
                )
            )
        return points
