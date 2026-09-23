"""Select on November/December only; optionally evaluate the frozen winner on January."""

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from wind_backend.model_selection import aggregate_metrics, select_winner

# Fixed before running experiments. January is deliberately absent from selection.
CANDIDATES = [
    dict(
        name="baseline",
        feature_set="scada",
        iterations=300,
        depth=6,
        learning_rate=0.05,
        loss_function="RMSE",
        l2_leaf_reg=3,
        origin_step_hours=24,
    ),
    dict(
        name="compact-mae",
        feature_set="scada",
        iterations=500,
        depth=4,
        learning_rate=0.04,
        loss_function="MAE",
        l2_leaf_reg=10,
        origin_step_hours=24,
    ),
    dict(
        name="extended-rmse",
        feature_set="scada-extended",
        iterations=500,
        depth=5,
        learning_rate=0.04,
        loss_function="RMSE",
        l2_leaf_reg=10,
        origin_step_hours=12,
    ),
    dict(
        name="extended-mae",
        feature_set="scada-extended",
        iterations=500,
        depth=5,
        learning_rate=0.04,
        loss_function="MAE",
        l2_leaf_reg=10,
        origin_step_hours=12,
    ),
]
FOLDS = [
    dict(name="november", cutoff="2025-11-01T00:00:00Z", end="2025-11-14T00:00:00Z"),
    dict(name="december", cutoff="2025-12-01T00:00:00Z", end="2025-12-14T00:00:00Z"),
]


def run_experiment(prepared, output, candidate, cutoff, end, register=False, resume=False):
    # A full day gap avoids crossing the cutoff even under delayed label availability.
    last = datetime.fromisoformat(cutoff) - timedelta(hours=72)
    command = [
        sys.executable,
        str(Path(__file__).with_name("train_evaluate.py")),
        "--prepared",
        str(prepared),
        "--output-root",
        str(output),
        "--trained-through",
        cutoff,
        "--first-origin",
        "2023-04-01T00:00:00Z",
        "--last-origin",
        last.isoformat(),
        "--validation-start",
        cutoff,
        "--validation-end",
        end,
    ]
    for key, value in candidate.items():
        if key != "name":
            command.extend(["--" + key.replace("_", "-"), str(value)])
    if register:
        command.append("--register")
    if output.exists():
        if (
            not resume
            or json.loads((output / "command.json").read_text(encoding="utf-8")) != command
        ):
            raise ValueError("Existing experiment requires --resume and an identical command")
    else:
        output.mkdir(parents=True, exist_ok=False)
        (output / "command.json").write_text(json.dumps(command, indent=2), encoding="utf-8")
    paths = list(output.glob("experiment-*/report.json"))
    if not paths:
        log = output / "console.log"
        if log.exists():
            log = output / f"console-retry-{uuid4().hex}.log"
        with log.open("x", encoding="utf-8") as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
    paths = list(output.glob("experiment-*/report.json"))
    if len(paths) != 1:
        raise ValueError("Expected exactly one completed experiment")
    report = json.loads(paths[0].read_text(encoding="utf-8"))
    if report["preparation"] != json.loads(
        (prepared / "preparation.json").read_text(encoding="utf-8")
    ):
        raise ValueError("Prepared data revision changed; start a new selection")
    comparison = report["comparison"]
    if comparison["catboost"]["scored_points"] != comparison["persistence"]["scored_points"]:
        raise ValueError("Candidates and baseline must use identical scoring coverage")
    return dict(report=str(paths[0]), model_id=report["model"]["id"], comparison=comparison)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/tuning"))
    parser.add_argument("--evaluate-january", action="store_true")
    parser.add_argument("--register", action="store_true")
    parser.add_argument(
        "--resume", type=Path, help="Resume interrupted folds before winner selection"
    )
    args = parser.parse_args()
    if args.register and not args.evaluate_january:
        parser.error("--register applies only to the frozen January model")
    output = args.resume or args.output_root / f"selection-{uuid4().hex}"
    plan = dict(
        created_at=datetime.now(UTC).isoformat(),
        candidates=CANDIDATES,
        folds=FOLDS,
        objective="pooled MAE; pooled RMSE tie-break; baseline is eligible",
        january_used_for_selection=False,
        random_seed=42,
        first_origin="2023-04-01T00:00:00Z",
        prepared=str(args.prepared),
    )
    if args.resume:
        saved = json.loads((output / "plan.json").read_text(encoding="utf-8"))
        plan["created_at"] = saved["created_at"]
        if plan != saved or (output / "selection.json").exists():
            parser.error("Resume requires an identical plan with no winner selected yet")
    else:
        output.mkdir(parents=True, exist_ok=False)
        (output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    results = []
    print(f"Frozen search plan: {output / 'plan.json'}", flush=True)
    for candidate in CANDIDATES:
        result = dict(candidate=candidate, folds=[])
        for fold in FOLDS:
            print(f"Training {candidate['name']} / {fold['name']}", flush=True)
            experiment = run_experiment(
                args.prepared,
                output / candidate["name"] / fold["name"],
                candidate,
                fold["cutoff"],
                fold["end"],
                resume=bool(args.resume),
            )
            result["folds"].append(dict(name=fold["name"], **experiment))
            print(aggregate_metrics(experiment["comparison"]["catboost"]["metrics"]), flush=True)
        result["pooled"] = aggregate_metrics(
            [
                metric
                for fold in result["folds"]
                for metric in fold["comparison"]["catboost"]["metrics"]
            ]
        )
        results.append(result)
        (output / "progress.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    winner = select_winner(results)
    selection = dict(
        plan=plan,
        results=results,
        selected=winner["candidate"],
        selected_at=datetime.now(UTC).isoformat(),
    )
    # Persist the decision BEFORE January evaluation; never revise it using January errors.
    (output / "selection.json").write_text(json.dumps(selection, indent=2), encoding="utf-8")
    print(f"Selected: {winner['candidate']['name']} {winner['pooled']}", flush=True)
    if args.evaluate_january:
        final = run_experiment(
            args.prepared,
            output / "january",
            winner["candidate"],
            "2026-01-01T00:00:00Z",
            "2026-01-28T00:00:00Z",
            args.register,
        )
        (output / "january.json").write_text(json.dumps(final, indent=2), encoding="utf-8")
        print(json.dumps(final, indent=2), flush=True)
    print(f"Selection report: {output / 'selection.json'}", flush=True)


if __name__ == "__main__":
    main()
