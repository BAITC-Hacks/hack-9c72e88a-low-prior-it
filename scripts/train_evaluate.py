"""Compare fixed CatBoost and training-only baselines on identical issue/target pairs."""

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter
from wind_backend.catboost_model import CatBoostPower
from wind_backend.config import Settings
from wind_backend.ml import PersistencePredictor
from wind_backend.service import WindService
from wind_backend.storage import Repository
from wind_backend.weather_experiment import (
    SCADA_PARAMETERS,
    TrainingBaselines,
    evaluate_comparison,
)
from wind_contracts.models import (
    DatasetUpload,
    Hour,
    Observation,
    TrainRequest,
    WeatherSnapshot,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--trained-through", required=True)
    parser.add_argument("--first-origin", required=True)
    parser.add_argument("--last-origin", required=True)
    parser.add_argument("--validation-start", required=True)
    parser.add_argument("--validation-end", required=True)
    parser.add_argument(
        "--feature-set", choices=["scada", "scada-extended", "weather-scada"], default="scada"
    )
    parser.add_argument("--weather", type=Path)
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--loss-function", choices=["RMSE", "MAE"], default="RMSE")
    parser.add_argument("--l2-leaf-reg", type=float, default=3)
    parser.add_argument("--origin-step-hours", type=int, choices=[6, 12, 24], default=24)
    parser.add_argument(
        "--register", action="store_true", help="Register dataset/models in the local API database"
    )
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/experiments"))
    args = parser.parse_args()
    start = TypeAdapter(Hour).validate_python(args.validation_start)
    end = TypeAdapter(Hour).validate_python(args.validation_end)
    cutoff = TypeAdapter(Hour).validate_python(args.trained_through)
    if start < cutoff or end < start or (end - start).total_seconds() % 86400:
        parser.error("Validation must start at/after cutoff and span whole days")
    # This tool is for pre-February model selection; competition scoring stays in /backtests.
    from datetime import timedelta

    if end + timedelta(hours=48) >= datetime(2026, 2, 1, tzinfo=UTC):
        parser.error(
            "Validation targets must precede February 2026; use /backtests for final scoring"
        )
    metadata = json.loads((args.prepared / "preparation.json").read_text(encoding="utf-8"))
    with (args.prepared / "observations.csv").open(encoding="utf-8", newline="") as source:
        rows = [Observation.model_validate(row) for row in csv.DictReader(source)]
    dataset = DatasetUpload(
        name=f"SCADA-{args.prepared.name}", is_demo=metadata["provisional"], observations=rows
    )
    snapshots = []
    if args.feature_set == "weather-scada":
        if args.weather is None:
            parser.error("weather-scada requires --weather with verified historical snapshots")
        snapshots = [
            WeatherSnapshot.model_validate(row)
            for row in json.loads(args.weather.read_text(encoding="utf-8"))
        ]
    run_id = f"experiment-{uuid4().hex}"
    output = args.output_root / run_id
    output.mkdir(parents=True, exist_ok=False)
    dataset_id = f"dataset-{uuid4().hex}"
    settings = Settings.from_env()
    service = None
    if args.register:
        service = WindService(
            Repository(settings.db_path), settings.turbines(), settings.models_path
        )
        dataset_id = service.upload_dataset(dataset).id
    request = TrainRequest(
        dataset_id=dataset_id,
        trained_through=cutoff,
        algorithm="catboost",
        feature_set=args.feature_set,
        first_origin=args.first_origin,
        last_origin=args.last_origin,
        iterations=args.iterations,
        depth=args.depth,
        learning_rate=args.learning_rate,
        loss_function=args.loss_function,
        l2_leaf_reg=args.l2_leaf_reg,
        origin_step_hours=args.origin_step_hours,
    )
    model_id = f"model-{uuid4().hex}"
    print(f"Training {args.feature_set} CatBoost, {len(rows)} hourly observations", flush=True)
    model = CatBoostPower.fit(model_id, rows, request, snapshots, is_demo=dataset.is_demo)
    artifact_root = settings.models_path if args.register else output / "models"
    artifact = model.save(artifact_root)
    # Evaluate the reloaded artifact, not only the in-memory estimator.
    model = CatBoostPower.load(artifact, artifact_root, rows)
    baseline = PersistencePredictor.fit(
        f"model-{uuid4().hex}", dataset_id, rows, cutoff, dataset.is_demo
    )
    models = {"catboost": model, "persistence": baseline}
    if args.feature_set == "weather-scada":
        scada_request = request.model_copy(
            update={key: value for key, value in SCADA_PARAMETERS.items() if key != "name"}
        )
        scada = CatBoostPower.fit(
            f"model-{uuid4().hex}", rows, scada_request, is_demo=dataset.is_demo
        )
        scada_artifact = scada.save(artifact_root)
        models["scada"] = CatBoostPower.load(scada_artifact, artifact_root, rows)
    baselines = TrainingBaselines(rows, cutoff, request.first_origin)
    comparison, exports = evaluate_comparison(
        rows,
        models,
        start,
        end,
        snapshots,
        baselines,
    )
    if not comparison["catboost"]["scored_points"]:
        raise ValueError("No validation actuals match the predictions")
    report = {
        "experiment_id": run_id,
        "provisional": dataset.is_demo,
        "preparation": metadata,
        "model": model.info.model_dump(mode="json"),
        "training": model.report,
        "validation_start": start.isoformat(),
        "validation_end": end.isoformat(),
        "weather_used": args.feature_set == "weather-scada",
        "comparison": comparison,
        "baseline_training": baselines.report(),
        "comparison_models": {
            name: fitted.info.model_dump(mode="json") for name, fitted in models.items()
        },
        "notes": [
            "Fixed model; chronological evaluation; no refitting or early stopping during evaluation.",
            "Each origin uses SCADA available by that origin, including earlier validation observations.",
            "Overlapping forecasts retained as separate issue/lead pairs; missing actuals unscored.",
            "Constant and turbine x UTC hour climatology are medians fixed using training data only.",
        ],
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (output / "predictions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(exports[0]))
        writer.writeheader()
        writer.writerows(exports)
    if service is not None:
        service.repository.put("model", model_id, artifact)
        service.repository.put(
            "model", baseline.info.id, {"info": baseline.info.model_dump(mode="json")}
        )
    print(
        json.dumps(
            {
                "report": str(output / "report.json"),
                "model_id": model_id,
                "persistence_model_id": baseline.info.id,
                "comparison": comparison,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
