"""Sample-weighted selection on chronological development folds only."""

from math import isfinite, sqrt


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
