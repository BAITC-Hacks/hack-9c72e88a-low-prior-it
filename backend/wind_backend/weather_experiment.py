"""Frozen chronological weather experiment shared by reproduce and CLI evaluation.

January is scored once after November/December selection. All comparison models
receive exactly the same issue/target pairs, including overlapping forecasts.
"""

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from statistics import median

from wind_agent.weather import target_hours
from wind_contracts.models import ForecastPoint, ForecastRequest, TrainRequest, Turbine

from wind_backend.catboost_model import (
    CatBoostPower,
    SnapshotIndex,
    daily_origins,
    history_digest,
)
from wind_backend.evaluation import evaluate
from wind_backend.features import ObservationHistory
from wind_backend.ml import PersistencePredictor
from wind_backend.model_selection import aggregate_metrics, select_winner

FIRST_ORIGIN = datetime(2024, 3, 15, 12, tzinfo=UTC)
JANUARY_CUTOFF = datetime(2026, 1, 1, tzinfo=UTC)
REFIT_CUTOFF = datetime(2026, 1, 31, 12, tzinfo=UTC)
RANDOM_SEED = 42
SCADA_PARAMETERS = dict(
    name="frozen-scada-compact-mae",
    feature_set="scada",
    iterations=500,
    depth=4,
    learning_rate=0.04,
    loss_function="MAE",
    l2_leaf_reg=10,
    origin_step_hours=24,
)
WEATHER_CANDIDATES = [
    dict(SCADA_PARAMETERS, name="weather-compact-mae", feature_set="weather-scada"),
    dict(SCADA_PARAMETERS, name="weather-depth6-mae", feature_set="weather-scada", depth=6),
    dict(
        SCADA_PARAMETERS,
        name="weather-depth6-rmse",
        feature_set="weather-scada",
        depth=6,
        iterations=300,
        loss_function="RMSE",
        learning_rate=0.05,
        l2_leaf_reg=3,
    ),
]
DEVELOPMENT_FOLDS = [
    dict(
        name="november",
        cutoff="2025-11-01T00:00:00Z",
        start="2025-11-01T12:00:00Z",
        end="2025-11-28T12:00:00Z",
    ),
    dict(
        name="december",
        cutoff="2025-12-01T00:00:00Z",
        start="2025-12-01T12:00:00Z",
        end="2025-12-29T12:00:00Z",
    ),
]


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def weather_input_digest(snapshots):
    """Stable input identity; local import time is not a meteorological input.

    Full snapshot checksums (including retrieved_at) remain in each training
    lineage record. Only the identity used for deterministic model IDs/cache
    keys omits that local audit timestamp.
    """
    return _digest(
        sorted(
            (snapshot.id, _digest(snapshot.model_dump(mode="json", exclude={"retrieved_at"})))
            for snapshot in snapshots
        )
    )


def training_implementation_digest():
    """Fingerprint training dependencies, independently of checkout path/Evidence UI.

    Normalize checkout line endings so a fresh Windows/Linux clone has the same
    identity. Any feature, label, selection, target or provenance-rule code change
    invalidates the shared model cache.
    """
    modules = (
        "wind_backend.catboost_model",
        "wind_backend.features",
        "wind_backend.weather_experiment",
        "wind_backend.model_selection",
        "wind_backend.evaluation",
        "wind_backend.ml",
        "wind_contracts.models",
        "wind_agent.orchestrator",
        "wind_agent.weather",
        "wind_agent.temporal",
    )
    return _digest(
        {
            name: hashlib.sha256(
                Path(import_module(name).__file__).read_text(encoding="utf-8").encode()
            ).hexdigest()
            for name in modules
        }
    )


class TrainingBaselines:
    """MAE-optimal constant and turbine x UTC target-hour climatology.

    Statistics use only observations within the training period, available by
    its cutoff. They remain fixed throughout evaluation.
    """

    def __init__(self, rows, cutoff, first_time=None):
        usable = [
            row
            for row in rows
            if row.valid_time <= cutoff
            and row.available_at <= cutoff
            and (first_time is None or row.valid_time >= first_time)
        ]
        if not usable:
            raise ValueError("Baselines need observations available by training cutoff")
        self.cutoff = cutoff
        self.constant = median(row.power_normalized for row in usable)
        groups = defaultdict(list)
        turbines = defaultdict(list)
        for row in usable:
            groups[row.turbine_id, row.valid_time.hour].append(row.power_normalized)
            turbines[row.turbine_id].append(row.power_normalized)
        self.climatology = {key: median(values) for key, values in groups.items()}
        self.fallback = {key: median(values) for key, values in turbines.items()}
        self.training_rows = len(usable)

    def predict_targets(self, turbine, targets, origin, name):
        if origin < self.cutoff:
            raise ValueError("Baseline prediction precedes training cutoff")
        if name not in ("constant", "climatology"):
            raise ValueError("Unknown training baseline")
        return [
            ForecastPoint(
                turbine_id=turbine.id,
                valid_time=target,
                lead_hours=int((target - origin).total_seconds() / 3600),
                power_normalized=(
                    self.constant
                    if name == "constant"
                    else self.climatology.get((turbine.id, target.hour), self.fallback[turbine.id])
                ),
            )
            for target in targets
        ]

    def report(self):
        return {
            "constant": self.constant,
            "climatology": {
                turbine: {
                    str(hour): value
                    for (t, hour), value in self.climatology.items()
                    if t == turbine
                }
                for turbine in sorted(self.fallback)
            },
            "training_rows": self.training_rows,
            "statistic": "median; climatology grouped by turbine and UTC target hour",
            "cutoff": self.cutoff.isoformat(),
        }


def evaluate_comparison(rows, models, start, end, snapshots=(), baselines=None):
    """Strict weather coverage, matched pairs, and per-model pair fingerprints."""
    index = snapshots if isinstance(snapshots, SnapshotIndex) else SnapshotIndex(snapshots)
    names = list(models) + (["constant", "climatology"] if baselines is not None else [])
    points = {name: [] for name in names}
    scored_pairs = {name: [] for name in names}
    exports = []
    actuals = {(row.turbine_id, row.valid_time) for row in rows}
    turbine_ids = sorted(next(iter(models.values())).info.turbine_ids)
    if any(sorted(model.info.turbine_ids) != turbine_ids for model in models.values()):
        raise ValueError("Comparison models must cover the same turbines")
    uses_weather = any(
        getattr(model, "feature_set", None) == "weather-scada" for model in models.values()
    )
    for origin in daily_origins(start, end):
        query = ForecastRequest(
            turbine_ids=turbine_ids, issued_at=origin, horizon_hours=48, weather_source="archive"
        )
        targets = target_hours(query)
        target_set = set(targets)
        for turbine_id in turbine_ids:
            turbine = Turbine(id=turbine_id, name=turbine_id)
            weather = None
            if uses_weather:
                snapshot = index.select(turbine, query)
                weather = [point for point in snapshot.points if point.valid_time in target_set]
            outputs = {}
            for name, model in models.items():
                if isinstance(model, CatBoostPower):
                    outputs[name] = model.predict_targets(turbine, targets, origin, weather)
                else:
                    outputs[name] = model.predict_targets(turbine, targets, origin)
            if baselines is not None:
                for name in ("constant", "climatology"):
                    outputs[name] = baselines.predict_targets(turbine, targets, origin, name)
            for name, output in outputs.items():
                if [point.valid_time for point in output] != targets or any(
                    point.turbine_id != turbine_id for point in output
                ):
                    raise ValueError("Comparison outputs must match every shared target")
                points[name].extend(output)
                for point in output:
                    if (point.turbine_id, point.valid_time) in actuals:
                        scored_pairs[name].append(
                            (turbine_id, origin.isoformat(), point.valid_time.isoformat())
                        )
                    exports.append(
                        {
                            "algorithm": name,
                            "issued_at": origin.isoformat(),
                            **point.model_dump(mode="json"),
                        }
                    )
    comparison = {}
    for name in names:
        metrics, scored, missing = evaluate(points[name], rows)
        groups = [metric.model_dump() for metric in metrics]
        comparison[name] = {
            "pooled": aggregate_metrics(groups),
            "metrics": groups,
            "scored_points": scored,
            "unscored_points": missing,
            "scored_pairs_sha256": _digest(sorted(scored_pairs[name])),
        }
    if len({entry["scored_pairs_sha256"] for entry in comparison.values()}) != 1:
        raise ValueError("Comparison models did not score the same issue/target pairs")
    return comparison, exports


def _request(dataset_id, cutoff, parameters):
    # Preserve daily 12UTC origins, leaving a whole-day margin before cutoff.
    last_origin = (cutoff - timedelta(hours=72)).replace(hour=12)
    return TrainRequest(
        dataset_id=dataset_id,
        algorithm="catboost",
        trained_through=cutoff,
        first_origin=FIRST_ORIGIN,
        last_origin=last_origin,
        random_seed=RANDOM_SEED,
        **{key: value for key, value in parameters.items() if key != "name"},
    )


def _training_summary(model):
    return {
        turbine: {
            **{key: value for key, value in report.items() if key != "weather_lineage"},
            "weather_origins": len(report["weather_lineage"]),
            "weather_lineage_sha256": _digest(report["weather_lineage"]),
        }
        for turbine, report in model.report["turbines"].items()
    }


def run_weather_experiment(
    rows,
    snapshots,
    preparation,
    dataset_id,
    progress=print,
    cache_root: Path | None = None,
):
    """Return report, January model, refit model; optionally persist checked caches.

    Cached model IDs include observations, weather archive, request and CatBoost
    version; loading checks both model bytes and the complete history digest.
    No model/hyperparameter is selected using January metrics.
    """
    from catboost import __version__ as catboost_version

    history_sha = history_digest(ObservationHistory(rows))
    weather_sha = weather_input_digest(snapshots)
    implementation_sha = training_implementation_digest()
    index = SnapshotIndex(snapshots)

    def train(parameters, cutoff):
        request = _request(dataset_id, cutoff, parameters)
        key = _digest(
            dict(
                request=request.model_dump(mode="json"),
                history=history_sha,
                weather=weather_sha,
                training_implementation_sha256=implementation_sha,
                catboost_version=catboost_version,
            )
        )[:24]
        identifier = f"model-weather-experiment-{key}"
        manifest = cache_root / identifier / "manifest.json" if cache_root else None
        if manifest is not None and manifest.exists():
            artifact = json.loads(manifest.read_text(encoding="utf-8"))
            if (
                artifact["report"]["request"] != request.model_dump(mode="json")
                or artifact["report"].get("weather_archive_sha256") != weather_sha
                or artifact["report"].get("training_implementation_sha256") != implementation_sha
            ):
                raise ValueError("Cached training provenance differs from requested experiment")
            model = CatBoostPower.load(artifact, cache_root, rows)
            progress(f"Loaded checked {parameters['name']} at {cutoff.isoformat()}", flush=True)
        else:
            progress(f"Training {parameters['name']} at {cutoff.isoformat()}", flush=True)
            model = CatBoostPower.fit(
                identifier, rows, request, index, is_demo=preparation["provisional"]
            )
            model.report["weather_archive_sha256"] = weather_sha
            model.report["training_implementation_sha256"] = implementation_sha
            if cache_root is not None:
                artifact = model.save(cache_root)
                model = CatBoostPower.load(artifact, cache_root, rows)
        return model

    plan = dict(
        candidates=WEATHER_CANDIDATES,
        folds=DEVELOPMENT_FOLDS,
        objective="pooled MAE on November/December only; pooled RMSE then candidate name tie-break",
        january_used_for_selection=False,
        random_seed=RANDOM_SEED,
        first_origin=FIRST_ORIGIN.isoformat(),
        issue_hour_utc=12,
        run_hour_utc=0,
    )
    results = []
    for candidate in WEATHER_CANDIDATES:
        folds = []
        for fold in DEVELOPMENT_FOLDS:
            cutoff = datetime.fromisoformat(fold["cutoff"])
            model = train(candidate, cutoff)
            persistence = PersistencePredictor.fit(
                "model-persistence-comparison",
                dataset_id,
                rows,
                cutoff,
                preparation["provisional"],
            )
            comparison, _ = evaluate_comparison(
                rows,
                {"catboost": model, "persistence": persistence},
                datetime.fromisoformat(fold["start"]),
                datetime.fromisoformat(fold["end"]),
                index,
            )
            folds.append(
                dict(
                    name=fold["name"],
                    model_id=model.info.id,
                    comparison=comparison,
                    training_summary=_training_summary(model),
                )
            )
        results.append(dict(candidate=candidate, folds=folds))
    winner = select_winner(results)["candidate"]
    selected_at = datetime.now(UTC).isoformat()
    selection = dict(plan=plan, results=results, selected=winner, selected_at=selected_at)
    progress(f"Frozen development winner: {winner['name']}", flush=True)
    january = train(winner, JANUARY_CUTOFF)
    scada = train(SCADA_PARAMETERS, JANUARY_CUTOFF)
    persistence = PersistencePredictor.fit(
        "model-persistence-comparison",
        dataset_id,
        rows,
        JANUARY_CUTOFF,
        preparation["provisional"],
    )
    baselines = TrainingBaselines(rows, JANUARY_CUTOFF, FIRST_ORIGIN)
    start = datetime(2026, 1, 1, 12, tzinfo=UTC)
    end = datetime(2026, 1, 29, 12, tzinfo=UTC)
    comparison, _ = evaluate_comparison(
        rows,
        {"weather_scada": january, "scada": scada, "persistence": persistence},
        start,
        end,
        index,
        baselines,
    )
    comparison = {
        name: comparison[name]
        for name in ("constant", "climatology", "persistence", "scada", "weather_scada")
    }
    refit = train(winner, REFIT_CUTOFF)
    report = dict(
        selection=selection,
        preparation=preparation,
        history_sha256=history_sha,
        weather_archive_sha256=weather_sha,
        training_implementation_sha256=implementation_sha,
        january=dict(
            model=january.info.model_dump(mode="json"),
            training_request=january.report["request"],
            training_summary=_training_summary(january),
            baseline_training=baselines.report(),
            scada_model=scada.info.model_dump(mode="json"),
            scada_training_request=scada.report["request"],
            selected_model="weather_scada",
            comparison=comparison,
            scored_pairs_sha256=comparison["weather_scada"]["scored_pairs_sha256"],
            unscored_points=comparison["weather_scada"]["unscored_points"],
            validation_start=start.isoformat(),
            validation_end=end.isoformat(),
        ),
        refit=dict(
            model=refit.info.model_dump(mode="json"),
            request=refit.report["request"],
            training_summary=_training_summary(refit),
            evaluation=None,
            selection_sha256=_digest(selection),
        ),
        notes=[
            "Weather candidates were fixed before fitting and selected using November/December only.",
            "January is a reused comparison period, not an untouched test or a tuning fold.",
            "All models score identical daily 12UTC issue/target pairs with 48 hourly leads; overlapping pairs are correlated.",
            "Constant and turbine x UTC hour climatology use training-period medians fixed at January 1; persistence uses only SCADA available at each origin.",
            "The SCADA comparison retains the previous compact MAE hyperparameters, refitted on the same daily origins and training start as the weather models.",
            "ECMWF archive includes 49R1 hindcasts; schedule-derived availability is an explicit assumption, not individually observed publication evidence.",
            "Reporting latency, source timezone semantics, normalization, rated power and hub height remain provisional.",
            "No February actual generation is supplied; February accuracy is not measured.",
        ],
    )
    return report, january, refit
