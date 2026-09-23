"""Reproducible JSON model artifacts. No HTTP and no pickle deserialization."""
from datetime import timedelta
from uuid import uuid4

import numpy as np

from wind_agent.interfaces import ForecastError
from wind_agent.orchestrator import fingerprint
from wind_contracts import ForecastPoint, ModelInfo, Observation, TrainRequest, WeatherSnapshot


def demo_model():
    info = ModelInfo(id="demo-power-curve", algorithm="illustrative-power-curve", demo=True,
                     fingerprint="demo-power-curve-v1", warnings=["Illustrative curve; not fitted to turbine observations"])
    return {"id": info.id, "info": info.model_dump(mode="json"), "parameters": {}}


def features(point, issue, last_power):
    speed = point.wind_speed_ms
    angle = np.deg2rad(point.wind_direction_deg)
    phase = 2 * np.pi * point.valid_time.hour / 24
    return [speed, speed ** 2, speed ** 3, point.temperature_c,
            np.sin(angle), np.cos(angle), (point.valid_time - issue).total_seconds() / 3600,
            np.sin(phase), np.cos(phase), last_power]


def latest_observation(rows, turbine_id, issue):
    candidates = [r for r in rows if r.turbine_id == turbine_id and r.valid_time <= issue and r.available_at <= issue]
    if not candidates:
        raise ForecastError("observations_unavailable", f"{turbine_id}: no observation available at issue time")
    return max(candidates, key=lambda r: r.valid_time)


def train(request: TrainRequest, dataset: dict, snapshots: list[WeatherSnapshot]):
    observations = [Observation.model_validate(r) for r in dataset["observations"]]
    rows = [r for r in observations if r.valid_time <= request.trained_through and r.available_at <= request.trained_through]
    if not rows:
        raise ForecastError("empty_training", "No observations available by model cutoff", 422)
    parameters, warnings = {}, []
    count = 0
    for turbine_id in sorted({r.turbine_id for r in rows}):
        selected = [r for r in rows if r.turbine_id == turbine_id]
        if request.algorithm == "binned-curve":
            ws = np.array([r.wind_speed_ms for r in selected])
            power = np.array([r.power_normalized for r in selected])
            centers, values = [], []
            for index in sorted(set(np.floor(ws / 0.5).astype(int))):
                mask = np.floor(ws / 0.5).astype(int) == index
                centers.append(float(index * 0.5 + 0.25))
                values.append(float(np.median(power[mask])))
            parameters[turbine_id] = {"centers": [0.0] + centers, "values": [0.0] + np.maximum.accumulate(values).tolist()}
            count += len(selected)
        elif request.algorithm == "persistence":
            parameters[turbine_id] = {}
            count += len(selected)
        else:
            # One row per original issue/valid/turbine pair. Publication is the earliest
            # defensible issue; round up to an hour, never use retrieved_at as publication.
            targets = {r.valid_time: r for r in selected}
            x, y, seen = [], [], set()
            for snapshot in sorted(snapshots, key=lambda s: (s.run_init, s.id), reverse=True):
                if (snapshot.turbine_id != turbine_id or snapshot.verification != "verified"
                        or snapshot.kind != "forecast" or snapshot.available_at is None):
                    continue
                issue = snapshot.available_at.replace(minute=0, second=0, microsecond=0)
                if issue < snapshot.available_at:
                    issue += timedelta(hours=1)
                if issue > request.trained_through:
                    continue
                try:
                    last = latest_observation(rows, turbine_id, issue)
                except ForecastError:
                    continue
                for point in snapshot.points:
                    lead = (point.valid_time - issue).total_seconds() / 3600
                    key = (issue, point.valid_time)
                    if 1 <= lead <= 48 and point.valid_time in targets and key not in seen:
                        x.append(features(point, issue, last.power_normalized))
                        y.append(targets[point.valid_time].power_normalized)
                        seen.add(key)
            if len(y) < 24:
                raise ForecastError("insufficient_weather_training", f"{turbine_id}: need at least 24 issue/valid pairs from verified forecasts", 422)
            x = np.array(x)
            mean, scale = x.mean(axis=0), x.std(axis=0)
            scale[scale < 1e-10] = 1
            design = np.column_stack([np.ones(len(x)), (x - mean) / scale])
            penalty = np.eye(design.shape[1]) * 10
            penalty[0, 0] = 0
            beta = np.linalg.solve(design.T @ design + penalty, design.T @ np.array(y))
            parameters[turbine_id] = {"mean": mean.tolist(), "scale": scale.tolist(), "beta": beta.tolist()}
            count += len(y)
    if request.algorithm == "binned-curve":
        warnings.append("SCADA wind curve applied to forecast wind; wind-height/site bias is not calibrated")
    if request.algorithm == "weather-ridge":
        warnings.append("Candidate ridge model; chronological validation required before operational use")
    model_id = f"model-{uuid4().hex}"
    digest = fingerprint({"request": request.model_dump(mode="json"), "dataset": dataset["info"]["fingerprint"],
                          "parameters": parameters, "weather": [s.model_dump(mode="json") for s in snapshots]})
    info = ModelInfo(id=model_id, algorithm=request.algorithm, demo=dataset["info"]["demo"],
        dataset_id=request.dataset_id, trained_through=request.trained_through, training_rows=count,
        turbine_ids=sorted(parameters), fingerprint=digest, warnings=warnings)
    return {"id": model_id, "info": info.model_dump(mode="json"), "parameters": parameters,
            "training_request": request.model_dump(mode="json")}


class ModelPredictor:
    def __init__(self, artifact: dict, observations: list[Observation] | None = None):
        self.info = ModelInfo.model_validate(artifact["info"])
        self.parameters = artifact["parameters"]
        self.observations = observations or []

    def predict(self, turbine, weather, issued_at):
        if self.info.trained_through and self.info.trained_through > issued_at:
            raise ForecastError("model_from_future", "Model cutoff is after issue time")
        params = self.parameters.get(turbine.id)
        if self.info.algorithm != "illustrative-power-curve" and params is None:
            raise ForecastError("untrained_turbine", f"No parameters for {turbine.id}")
        last = None
        if self.info.algorithm in ("persistence", "weather-ridge"):
            last = latest_observation(self.observations, turbine.id, issued_at)
        out = []
        for point in weather.points:
            if self.info.algorithm == "illustrative-power-curve":
                value = np.clip((point.wind_speed_ms - 3) / 9, 0, 1) ** 3
            elif self.info.algorithm == "binned-curve":
                value = np.interp(point.wind_speed_ms, params["centers"], params["values"])
            elif self.info.algorithm == "persistence":
                value = last.power_normalized
            else:
                x = (np.array(features(point, issued_at, last.power_normalized)) - params["mean"]) / params["scale"]
                value = np.dot(np.r_[1, x], params["beta"])
            # Model outputs are explicitly bounded; imported observations are never clipped.
            out.append(ForecastPoint(turbine_id=turbine.id, valid_time=point.valid_time,
                lead_hours=int((point.valid_time - issued_at).total_seconds() / 3600), power_normalized=float(np.clip(value, 0, 1))))
        return out
