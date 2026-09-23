"""Sample-weighted selection on chronological development folds only."""

from datetime import datetime, timedelta
from math import isfinite, sqrt

from pydantic import TypeAdapter
from wind_contracts.models import Hour, TrainRequest


def aggregate_metrics(metrics):
    if not metrics or any(
        row["samples"] <= 0
        or not isfinite(row["mae"])
        or not isfinite(row["rmse"])
        or row["mae"] < 0
        or row["rmse"] < 0
        for row in metrics
    ):
        raise ValueError("Selection requires finite metrics and positive sample counts")
    samples = sum(row["samples"] for row in metrics)
    return dict(
        samples=samples,
        mae=sum(row["samples"] * row["mae"] for row in metrics) / samples,
        rmse=sqrt(sum(row["samples"] * row["rmse"] ** 2 for row in metrics) / samples),
    )


def select_winner(results):
    if not results:
        raise ValueError("No completed candidates")
    # Compare every turbine/horizon/fold count, not merely equal grand totals.
    coverages = [
        [
            (fold["name"], m["turbine_id"], m["horizon"], m["samples"])
            for fold in result["folds"]
            for m in fold["comparison"]["catboost"]["metrics"]
        ]
        for result in results
    ]
    if any(sorted(coverage) != sorted(coverages[0]) for coverage in coverages):
        raise ValueError("Candidates must have identical fold and target coverage")
    for result in results:
        result["pooled"] = aggregate_metrics(
            [m for fold in result["folds"] for m in fold["comparison"]["catboost"]["metrics"]]
        )
    return min(
        results, key=lambda r: (r["pooled"]["mae"], r["pooled"]["rmse"], r["candidate"]["name"])
    )


def refit_request(selection, dataset_id, cutoff):
    cutoff = TypeAdapter(Hour).validate_python(cutoff)
    winner = select_winner(selection["results"])["candidate"]
    if selection["plan"]["january_used_for_selection"] or winner != selection["selected"]:
        raise ValueError("Selection must match the frozen development-fold winner")
    last_development_target = max(
        datetime.fromisoformat(fold["end"]) + timedelta(hours=48)
        for fold in selection["plan"]["folds"]
    )
    if cutoff <= last_development_target:
        raise ValueError("Refit cutoff must follow all development targets")
    return TrainRequest(
        dataset_id=dataset_id,
        algorithm="catboost",
        trained_through=cutoff,
        first_origin=selection["plan"]["first_origin"],
        last_origin=cutoff - timedelta(hours=72),
        random_seed=selection["plan"]["random_seed"],
        **{key: value for key, value in winner.items() if key != "name"},
    )
