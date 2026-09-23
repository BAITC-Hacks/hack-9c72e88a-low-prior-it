"""Refit a frozen selected configuration for a later forecast issue; register locally."""

import argparse
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from wind_backend.catboost_model import history_digest
from wind_backend.config import Settings
from wind_backend.features import ObservationHistory
from wind_backend.model_selection import refit_request
from wind_backend.service import WindService
from wind_backend.storage import Repository
from wind_contracts.models import DatasetUpload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--trained-through", required=True)
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/refits"))
    args = parser.parse_args()
    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    request = refit_request(selection, args.dataset_id, args.trained_through)
    settings = Settings.from_env()
    service = WindService(Repository(settings.db_path), settings.turbines(), settings.models_path)
    dataset = DatasetUpload.model_validate(service.required("dataset", args.dataset_id)["data"])
    reference = json.loads(
        Path(selection["results"][0]["folds"][0]["report"]).read_text(encoding="utf-8")
    )
    if (
        history_digest(ObservationHistory(dataset.observations))
        != reference["training"]["history_sha256"]
    ):
        raise ValueError("Refit requires the same immutable observation history as selection")
    output = args.output_root / f"refit-{uuid4().hex}"
    output.mkdir(parents=True, exist_ok=False)
    (output / "request.json").write_text(request.model_dump_json(indent=2), encoding="utf-8")
    print(
        f"Refitting {selection['selected']['name']} through {request.trained_through}", flush=True
    )
    info = service.train(request)
    report = dict(
        model=info.model_dump(mode="json"),
        request=request.model_dump(mode="json"),
        selection=str(args.selection),
        selection_sha256=hashlib.sha256(args.selection.read_bytes()).hexdigest(),
        training=service.required("model", info.id)["report"],
        evaluation=None,
        notes=[
            "Refit on later history, using the frozen development-fold winner.",
            "Earlier January metrics do not evaluate these refitted weights.",
            "Forecasts must be issued at or after this model's training cutoff.",
        ],
    )
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(dict(report=str(output / "report.json"), model=report["model"]), indent=2),
        flush=True,
    )


if __name__ == "__main__":
    main()
