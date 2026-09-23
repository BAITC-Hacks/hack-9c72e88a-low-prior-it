"""Project recorded experiments into an auditable public report without retraining."""

import hashlib
import json
from datetime import timedelta
from math import isclose, sqrt
from pathlib import Path, PureWindowsPath

from pydantic import TypeAdapter
from wind_contracts.evidence import (
    EvidenceCandidate,
    EvidenceFold,
    EvidenceMetric,
    EvidenceModel,
    EvidenceReport,
    EvidenceScore,
    EvidenceSource,
    EvidenceWeather,
    Sha256,
)
from wind_contracts.models import Hour

from wind_backend.service import DomainError

EVIDENCE_PATH = Path(__file__).resolve().parents[2] / "docs" / "model-selection-results.json"
_HOUR = TypeAdapter(Hour)
_SHA256 = TypeAdapter(Sha256)


def pooled_score(groups: list[EvidenceMetric] | list[EvidenceScore]) -> EvidenceScore:
    """Pool errors by sample count; RMSE pools squared error, not group roots."""
    samples = sum(group.samples for group in groups)
    if not samples:
        raise ValueError("Evidence requires scored samples")
    return EvidenceScore(
        samples=samples,
        mae=sum(group.mae * group.samples for group in groups) / samples,
        rmse=sqrt(sum(group.rmse**2 * group.samples for group in groups) / samples),
    )


def _metrics(values) -> list[EvidenceMetric]:
    metrics = [EvidenceMetric.model_validate(value) for value in values]
    if len({(m.turbine_id, m.horizon) for m in metrics}) != len(metrics):
        raise ValueError("Duplicate evidence metric cells")
    return metrics


def _coverage(metrics):
    return sorted((m.turbine_id, m.horizon, m.samples) for m in metrics)


def _verify_pooled(recorded, calculated):
    expected = EvidenceScore.model_validate(recorded)
    if expected.samples != calculated.samples or any(
        not isclose(getattr(expected, key), getattr(calculated, key), abs_tol=1e-10)
        for key in ("mae", "rmse")
    ):
        raise ValueError("Recorded aggregate differs from its scored groups")


def _issue_count(start, end):
    days = (end - start).total_seconds() / 86400
    if days < 0 or not days.is_integer():
        raise ValueError("Evidence issues must be daily and ordered")
    return int(days) + 1


def _build_report(source, digest):
    selection = source["selection"]
    plan = selection["plan"]
    january = source["january"]
    preparation = source["preparation"]
    if plan["january_used_for_selection"] is not False or preparation["provisional"] is not True:
        raise ValueError("Evidence assumptions changed; review the published report contract")
    if source["refit"]["evaluation"] is not None:
        raise ValueError("A newly evaluated refit requires an updated evidence report")

    first_issue = _HOUR.validate_python(january["validation_start"])
    last_issue = _HOUR.validate_python(january["validation_end"])
    cutoff = _HOUR.validate_python(january["model"]["trained_through"])
    training = january["training_request"]
    weather_comparison = "weather_scada" in january["comparison"]
    selected_model = january.get("selected_model", "selected")
    if (
        cutoff > first_issue
        or _HOUR.validate_python(training["trained_through"]) != cutoff
        or _HOUR.validate_python(training["last_origin"]) + timedelta(hours=48) > cutoff
        or training["horizon_hours"] != 48
        or training["feature_set"] not in {"scada", "scada-extended", "weather-scada"}
        or training["feature_set"] != selection["selected"]["feature_set"]
        or january["model"]["algorithm"] != f"catboost-{training['feature_set']}-v1"
    ):
        raise ValueError("Evidence training/evaluation boundaries are inconsistent")
    models = []
    expected_coverage = None
    model_labels = (
        ("constant", "Constant (training median)"),
        ("climatology", "Climatology (turbine × UTC hour)"),
        ("persistence", "Persistence"),
        ("scada", "CatBoost SCADA"),
        ("weather_scada", "CatBoost weather + SCADA"),
    ) if weather_comparison else (
        ("selected", "Selected CatBoost"),
        ("previous", "Previous CatBoost"),
        ("persistence", "Persistence"),
    )
    if selected_model not in {identifier for identifier, _ in model_labels}:
        raise ValueError("Selected model is missing from the comparison")
    if weather_comparison and (
        selected_model != "weather_scada" or training["feature_set"] != "weather-scada"
    ):
        raise ValueError("Weather comparison must identify its selected weather model")
    if weather_comparison:
        scada_training = january["scada_training_request"]
        if (
            _HOUR.validate_python(january["baseline_training"]["cutoff"]) != cutoff
            or _HOUR.validate_python(january["scada_model"]["trained_through"]) != cutoff
            or _HOUR.validate_python(scada_training["trained_through"]) != cutoff
            or _HOUR.validate_python(scada_training["last_origin"]) + timedelta(hours=48) > cutoff
            or scada_training["feature_set"] != "scada"
            or scada_training["horizon_hours"] != 48
        ):
            raise ValueError("Baseline and SCADA comparisons require the same training cutoff")
    for identifier, label in model_labels:
        comparison = january["comparison"][identifier]
        metrics = _metrics(comparison["metrics"])
        pooled = pooled_score(metrics)
        _verify_pooled(comparison["pooled"], pooled)
        coverage = _coverage(metrics)
        if expected_coverage is not None and expected_coverage != coverage:
            raise ValueError("Model comparisons require identical scored cells")
        expected_coverage = coverage
        pair_digest = comparison.get("scored_pairs_sha256")
        if weather_comparison and (
            not pair_digest
            or pair_digest != january["scored_pairs_sha256"]
            or comparison["scored_points"] != pooled.samples
            or comparison["unscored_points"] != january["unscored_points"]
        ):
            raise ValueError("Model comparisons require identical scored issue/target pairs")
        models.append(EvidenceModel(
            id=identifier, label=label, selected=identifier == selected_model,
            scored_pairs_sha256=pair_digest, pooled=pooled, metrics=metrics,
        ))

    turbine_ids = {m.turbine_id for m in models[0].metrics}
    scored_pairs = models[0].pooled.samples
    expected_pairs = _issue_count(first_issue, last_issue) * 48 * len(turbine_ids)
    if {(m.turbine_id, m.horizon) for m in models[0].metrics} != {
        (turbine_id, horizon)
        for turbine_id in turbine_ids for horizon in ("1-24", "25-48")
    }:
        raise ValueError("Every turbine needs both lead windows")
    if scored_pairs + january["unscored_points"] != expected_pairs:
        raise ValueError("January coverage does not match the issue/horizon window")

    fold_plan = {fold["name"]: fold for fold in plan["folds"]}
    candidate_plan = {candidate["name"]: candidate for candidate in plan["candidates"]}
    if len(fold_plan) != len(plan["folds"]) or len(candidate_plan) != len(plan["candidates"]):
        raise ValueError("Duplicate selection plan entries")
    candidates = []
    fold_coverages = {}
    fold_pair_digests = {}
    for result in selection["results"]:
        candidate = result["candidate"]
        if candidate != candidate_plan[candidate["name"]]:
            raise ValueError("Candidate parameters differ from selection plan")
        folds = []
        for fold in result["folds"]:
            specification = fold_plan[fold["name"]]
            fold_cutoff = _HOUR.validate_python(specification["cutoff"])
            start = _HOUR.validate_python(specification.get("start", specification["cutoff"]))
            end = _HOUR.validate_python(specification["end"])
            if start < fold_cutoff or end + timedelta(hours=48) > first_issue:
                raise ValueError("Development target period overlaps January comparison")
            if weather_comparison and (start.hour != first_issue.hour or end.hour != first_issue.hour):
                raise ValueError("Development and January must use the same issue hour")
            comparison = fold["comparison"]["catboost"]
            metrics = _metrics(comparison["metrics"])
            baseline = _metrics(fold["comparison"]["persistence"]["metrics"])
            coverage = _coverage(metrics)
            if coverage != _coverage(baseline):
                raise ValueError("Development baselines require matching scored cells")
            if "pooled" in comparison:
                _verify_pooled(comparison["pooled"], pooled_score(metrics))
            if "pooled" in fold["comparison"]["persistence"]:
                _verify_pooled(fold["comparison"]["persistence"]["pooled"], pooled_score(baseline))
            if fold["name"] in fold_coverages and fold_coverages[fold["name"]] != coverage:
                raise ValueError("Candidates require identical development coverage")
            fold_coverages[fold["name"]] = coverage
            if weather_comparison:
                pair_digest = comparison.get("scored_pairs_sha256")
                if (
                    not pair_digest
                    or pair_digest != fold["comparison"]["persistence"].get("scored_pairs_sha256")
                    or pair_digest != fold_pair_digests.get(fold["name"], pair_digest)
                ):
                    raise ValueError("Candidates require identical development issue/target pairs")
                _SHA256.validate_python(pair_digest)
                fold_pair_digests[fold["name"]] = pair_digest
            pooled = pooled_score(metrics)
            expected_pairs = _issue_count(start, end) * 48 * len(turbine_ids)
            if (
                comparison["scored_points"] != pooled.samples
                or pooled.samples + comparison["unscored_points"] != expected_pairs
            ):
                raise ValueError("Development sample counts are inconsistent")
            folds.append(
                EvidenceFold(
                    name=fold["name"],
                    first_issue=start,
                    last_issue=end,
                    pooled=pooled,
                    scored_pairs=pooled.samples,
                    unscored_pairs=comparison["unscored_points"],
                )
            )
        if sorted(f.name for f in folds) != sorted(fold_plan):
            raise ValueError("Candidate must include every development fold exactly once")
        pooled = pooled_score([fold.pooled for fold in folds])
        _verify_pooled(result["pooled"], pooled)
        candidates.append(
            EvidenceCandidate(
                name=candidate["name"],
                selected=candidate == selection["selected"],
                feature_set=candidate["feature_set"],
                iterations=candidate["iterations"],
                depth=candidate["depth"],
                loss_function=candidate["loss_function"],
                pooled=pooled,
                folds=folds,
            )
        )
    if sorted(c.name for c in candidates) != sorted(candidate_plan):
        raise ValueError("Evidence must contain all planned candidates exactly once")
    selected = [candidate for candidate in candidates if candidate.selected]
    if (
        len(selected) != 1
        or min(candidates, key=lambda c: (c.pooled.mae, c.pooled.rmse, c.name)) != selected[0]
    ):
        raise ValueError("Recorded selection does not minimize pooled MAE")
    if any(training[key] != value for key, value in selection["selected"].items() if key != "name"):
        raise ValueError("January parameters differ from the recorded selection")

    sources = []
    for entry in preparation["sources"]:
        profile = preparation["profiles"][entry["turbine_id"]]
        sources.append(
            EvidenceSource(
                turbine_id=entry["turbine_id"],
                source_file=PureWindowsPath(entry["source"]).name,
                sha256=entry["sha256"],
                rows=entry["source_rows"],
                complete_hours=profile["complete_hours"],
                incomplete_hours=profile["incomplete_hours"],
                missing_slots=profile["missing_slots"],
            )
        )
    if {entry.turbine_id for entry in sources} != turbine_ids or len(sources) != len(turbine_ids):
        raise ValueError("Source provenance must match the evaluated turbines")
    refit = source["refit"]["model"]
    refit_request = source["refit"]["request"]
    refit_cutoff = _HOUR.validate_python(refit["trained_through"])
    if (
        refit_cutoff <= last_issue
        or _HOUR.validate_python(refit_request["trained_through"]) != refit_cutoff
        or _HOUR.validate_python(refit_request["last_origin"]) + timedelta(hours=48) > refit_cutoff
        or refit_request["feature_set"] != training["feature_set"]
        or any(refit_request[key] != value for key, value in selection["selected"].items()
               if key != "name")
    ):
        raise ValueError("Refit and evaluated model boundaries are inconsistent")
    weather = EvidenceWeather.model_validate({
        key: source["weather"][key] for key in EvidenceWeather.model_fields
    }) if source.get("weather") else None
    if weather_comparison and weather is None:
        raise ValueError("Weather model evidence requires weather provenance")
    if weather is not None and (
        weather.issue_hour_utc != first_issue.hour
        or weather.issue_hour_utc != last_issue.hour
        or weather.run_hour_utc + weather.publication_delay_hours > weather.issue_hour_utc
    ):
        raise ValueError("Weather availability assumption must precede forecast issue time")
    return EvidenceReport(
        source_file=EVIDENCE_PATH.name,
        source_sha256=digest,
        selected_at=selection["selected_at"],
        benchmark={
            "name": "January reused comparison",
            "first_issue": first_issue,
            "last_issue": last_issue,
            "trained_through": cutoff,
            "feature_set": training["feature_set"],
            "scored_pairs": scored_pairs,
            "unscored_pairs": january["unscored_points"],
            "models": models,
        },
        selection={
            "objective": plan["objective"],
            "first_training_origin": plan["first_origin"],
            "candidates": candidates,
        },
        data={
            "complete_hours": sum(entry.complete_hours for entry in sources),
            "timezone": preparation["timezone"],
            "timestamp_position": preparation["timestamp_position"],
            "latency_minutes": preparation["latency_minutes"],
            "history_sha256": source["history_sha256"],
            "sources": sources,
        },
        weather=weather,
        refit={
            "trained_through": refit["trained_through"],
            "training_rows": refit["training_rows"],
        },
        checkpoints=[
            {
                "id": "chronology",
                "status": "verified",
                "title": "Chronological selection recorded",
                "detail": f"{len(candidates)} planned candidates use chronological development folds. January was reused for comparison after selection; it is not an untouched test.",
            },
            {
                "id": "comparability",
                "status": "verified",
                "title": "Matched comparison coverage",
                "detail": f"All {len(models)} models report the same {scored_pairs:,} scored issue/target pairs, grouped by turbine and horizon. {'Pair fingerprints also match. ' if weather_comparison else ''}Overlapping pairs are correlated.",
            },
            {
                "id": "lineage",
                "status": "verified",
                "title": "Source fingerprints recorded",
                "detail": "The committed summary records source and prepared-history SHA-256 hashes. Raw readings and individual predictions are not included in this report.",
            },
            {
                "id": "assumptions",
                "status": "provisional",
                "title": "Recorded preparation is provisional",
                "detail": "This experiment records assumed 10-minute reporting latency and unconfirmed physical power normalization. These are the experiment's recorded assumptions, not a fresh assessment of current data.",
            },
            {
                "id": "february",
                "status": "open",
                "title": "February evaluation remains open",
                "detail": "The later January 31 refit has no measured February score in this evidence. January metrics belong to the January 1 model only.",
            },
        ],
        limitations=source["notes"]
        + (weather.limitations if weather else [])
        + [
            "This endpoint presents a committed experiment summary; it does not run a new evaluation or verify local model deployment.",
            "MAE and RMSE are normalized-power errors on [0,1], not accuracy percentages or energy/money savings.",
            "Selection minimizes pooled development MAE with pooled RMSE as a tie-break; January is not used to select hyperparameters.",
            "Two development folds and a reused January comparison do not establish general superiority across seasons. No calibrated uncertainty or significance claim is available.",
        ] + ([] if weather_comparison else [
            "This legacy experiment uses SCADA features only. Demo weather in its integration smoke check is not weather-forecast accuracy evidence.",
        ]),
    )


def load_evidence() -> EvidenceReport:
    try:
        payload = EVIDENCE_PATH.read_bytes()
        return _build_report(json.loads(payload), hashlib.sha256(payload).hexdigest())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DomainError(
            503,
            "evidence_unavailable",
            "The committed model evidence is missing or invalid. Restore the reviewed report to display results.",
        ) from exc
