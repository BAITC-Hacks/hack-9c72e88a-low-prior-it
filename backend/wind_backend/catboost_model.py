"""Local per-turbine CatBoost models with identical training/inference feature code."""

import hashlib
import json
import math
from datetime import timedelta
from pathlib import Path

from catboost import CatBoostRegressor, Pool
from catboost import __version__ as catboost_version
from wind_agent.orchestrator import ForecastAgent
from wind_agent.weather import target_hours
from wind_contracts.models import ForecastPoint, ForecastRequest, ModelInfo, TrainRequest, Turbine

from wind_backend.features import (
    FEATURE_NAMES,
    FEATURE_VERSION,
    SCADA_FEATURE_NAMES,
    ObservationHistory,
    build_features,
    build_scada_features,
)
from wind_backend.ml import validate_model_origin


def select_snapshot(snapshots, turbine, request):
    """Use the same deterministic provenance and coverage rules as the agent."""
    candidates = []
    for snapshot in snapshots:
        try:
            ForecastAgent.validate_snapshot(snapshot, turbine, request)
        except ValueError:
            continue
        candidates.append(snapshot)
    if not candidates:
        raise ValueError(
            f"{turbine.id}: no eligible complete weather at {request.issued_at.isoformat()}"
        )
    return max(candidates, key=lambda s: (s.run_init, s.available_at, s.retrieved_at, s.id))


def daily_origins(first, last):
    origin = first
    while origin <= last:
        yield origin
        origin += timedelta(days=1)


def history_digest(history):
    digest = hashlib.sha256()
    for row in history.rows:
        digest.update(row.model_dump_json().encode())
        digest.update(b"\n")
    return digest.hexdigest()


class CatBoostPower:
    def __init__(self, info, models, history, feature_set, report):
        self.info = info
        self.models = models
        self.history = history
        self.feature_set = feature_set
        self.report = report

    @classmethod
    def fit(cls, identifier, rows, request: TrainRequest, snapshots=(), is_demo=False):
        request = TrainRequest.model_validate(request.model_dump())
        if request.algorithm != "catboost":
            raise ValueError("CatBoost training requires algorithm=catboost")
        if (
            request.feature_set == "weather-scada"
            and request.weather_source == "demo"
            and not is_demo
        ):
            raise ValueError("Synthetic weather training requires an explicitly demo dataset")
        history = ObservationHistory(rows)
        labels = {
            (r.turbine_id, r.valid_time): r
            for r in history.rows
            if r.valid_time <= request.trained_through and r.available_at <= request.trained_through
        }
        turbines = sorted({t for t, _ in labels})
        if not turbines:
            raise ValueError("No observations available by training cutoff")
        names = FEATURE_NAMES if request.feature_set == "weather-scada" else SCADA_FEATURE_NAMES
        models, report, total = {}, {}, 0
        parameters = dict(
            iterations=request.iterations,
            depth=request.depth,
            learning_rate=request.learning_rate,
            random_seed=request.random_seed,
            loss_function="RMSE",
            thread_count=2,
            task_type="CPU",
            allow_writing_files=False,
            verbose=False,
        )
        for turbine_id in turbines:
            x, y, lineage, skipped = [], [], [], 0
            for origin in daily_origins(request.first_origin, request.last_origin):
                query = ForecastRequest(
                    turbine_ids=[turbine_id],
                    issued_at=origin,
                    horizon_hours=request.horizon_hours,
                    weather_source=request.weather_source,
                )
                targets = target_hours(query)
                if request.feature_set == "weather-scada":
                    snapshot = select_snapshot(
                        snapshots, Turbine(id=turbine_id, name=turbine_id), query
                    )
                    weather = [p for p in snapshot.points if p.valid_time in set(targets)]
                    features = build_features(history, turbine_id, weather, origin)
                    lineage.append(
                        {
                            "origin": origin.isoformat(),
                            "snapshot_id": snapshot.id,
                            "run_init": snapshot.run_init.isoformat(),
                            "available_at": snapshot.available_at.isoformat(),
                            "sha256": hashlib.sha256(
                                snapshot.model_dump_json().encode()
                            ).hexdigest(),
                        }
                    )
                else:
                    features = build_scada_features(history, turbine_id, targets, origin)
                for target, feature in zip(targets, features, strict=True):
                    label = labels.get((turbine_id, target))
                    if label is None:
                        skipped += 1
                        continue
                    x.append(feature)
                    y.append(label.power_normalized)
            if len(y) < 48 or len(set(y)) < 2:
                raise ValueError(
                    f"{turbine_id}: need at least 48 available training samples and varying power"
                )
            model = CatBoostRegressor(**parameters)
            model.fit(Pool(x, label=y, feature_names=names))
            models[turbine_id] = model
            total += len(y)
            report[turbine_id] = {
                "training_samples": len(y),
                "missing_or_late_targets": skipped,
                "weather_lineage": lineage,
                "feature_importance": dict(
                    zip(names, map(float, model.feature_importances_), strict=True)
                ),
            }
        info = ModelInfo(
            id=identifier,
            algorithm=f"catboost-{request.feature_set}-v1",
            trained_through=request.trained_through,
            dataset_id=request.dataset_id,
            training_rows=total,
            turbine_ids=turbines,
            is_demo=is_demo,
        )
        return cls(
            info,
            models,
            history,
            request.feature_set,
            {
                "feature_version": FEATURE_VERSION,
                "features": names,
                "catboost_version": catboost_version,
                "parameters": parameters,
                "request": request.model_dump(mode="json"),
                "history_sha256": history_digest(history),
                "turbines": report,
                "output_transform": "clip ML output to [0,1]; no LLM changes",
                "history_policy": "immutable dataset; valid_time AND available_at <= each origin",
            },
        )

    def predict_targets(self, turbine, targets, issued_at, weather=None):
        origin = validate_model_origin(self.info, issued_at)
        if turbine.id not in self.models:
            raise ValueError(f"Model was not trained for {turbine.id}")
        if self.feature_set == "weather-scada":
            if weather is None or [p.valid_time for p in weather] != targets:
                raise ValueError("Weather features must match every prediction target")
            features = build_features(self.history, turbine.id, weather, origin)
        else:
            features = build_scada_features(self.history, turbine.id, targets, origin)
        values = self.models[turbine.id].predict(features)
        points = []
        for target, value in zip(targets, values, strict=True):
            if not math.isfinite(value):
                raise ValueError("CatBoost returned nonfinite power")
            points.append(
                ForecastPoint(
                    turbine_id=turbine.id,
                    valid_time=target,
                    lead_hours=int((target - origin).total_seconds() / 3600),
                    power_normalized=round(max(0.0, min(1.0, float(value))), 6),
                )
            )
        return points

    def predict(self, turbine, weather, issued_at):
        return self.predict_targets(turbine, [p.valid_time for p in weather], issued_at, weather)

    def save(self, root: Path):
        directory = root / self.info.id
        directory.mkdir(parents=True, exist_ok=False)
        files = {}
        for turbine_id, model in self.models.items():
            path = directory / f"{turbine_id}.cbm"
            model.save_model(str(path))
            files[turbine_id] = {
                "filename": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        artifact = {
            "info": self.info.model_dump(mode="json"),
            "feature_set": self.feature_set,
            "models": files,
            "report": self.report,
        }
        (directory / "manifest.json").write_text(
            json.dumps(artifact, indent=2, allow_nan=False), encoding="utf-8"
        )
        return artifact

    @classmethod
    def load(cls, artifact, root, rows):
        info = ModelInfo.model_validate(artifact["info"])
        history = ObservationHistory(rows)
        if history_digest(history) != artifact["report"]["history_sha256"]:
            raise ValueError("Model observation history checksum mismatch")
        if artifact["report"]["feature_version"] != FEATURE_VERSION:
            raise ValueError("Unsupported model feature version; retrain the model")
        models = {}
        directory = (root / info.id).resolve()
        for turbine_id, entry in artifact["models"].items():
            path = (directory / entry["filename"]).resolve()
            if (
                path.parent != directory
                or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]
            ):
                raise ValueError("CatBoost artifact path or checksum mismatch")
            model = CatBoostRegressor()
            model.load_model(str(path))
            models[turbine_id] = model
        if set(models) != set(info.turbine_ids):
            raise ValueError("CatBoost artifact turbine coverage mismatch")
        return cls(info, models, history, artifact["feature_set"], artifact["report"])
