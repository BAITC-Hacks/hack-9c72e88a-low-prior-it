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
)
from wind_contracts.models import Hour

from wind_backend.service import DomainError

EVIDENCE_PATH = Path(__file__).resolve().parents[2] / "docs" / "model-selection-results.json"
_HOUR = TypeAdapter(Hour)


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
    if (
        cutoff > first_issue
        or _HOUR.validate_python(training["trained_through"]) != cutoff
        or _HOUR.validate_python(training["last_origin"]) + timedelta(hours=48) > cutoff
        or training["horizon_hours"] != 48
        or training["feature_set"] != "scada"
        or january["model"]["is_demo"] is not True
    ):
        raise ValueError("Evidence training/evaluation boundaries are inconsistent")
    models = []
    expected_coverage = None
    for identifier, label in (
        ("selected", "Selected CatBoost"),
        ("previous", "Previous CatBoost"),
        ("persistence", "Persistence"),
    ):
        comparison = january["comparison"][identifier]
        metrics = _metrics(comparison["metrics"])
        pooled = pooled_score(metrics)
        _verify_pooled(comparison["pooled"], pooled)
        coverage = _coverage(metrics)
        if expected_coverage is not None and expected_coverage != coverage:
            raise ValueError("Model comparisons require identical scored cells")
        expected_coverage = coverage
        models.append(EvidenceModel(id=identifier, label=label, pooled=pooled, metrics=metrics))

    turbine_ids = {m.turbine_id for m in models[0].metrics}
    scored_pairs = models[0].pooled.samples
    expected_pairs = _issue_count(first_issue, last_issue) * 48 * len(turbine_ids)
    if scored_pairs + january["unscored_points"] != expected_pairs:
        raise ValueError("January coverage does not match the issue/horizon window")

    fold_plan = {fold["name"]: fold for fold in plan["folds"]}
    candidate_plan = {candidate["name"]: candidate for candidate in plan["candidates"]}
    if len(fold_plan) != len(plan["folds"]) or len(candidate_plan) != len(plan["candidates"]):
        raise ValueError("Duplicate selection plan entries")
    candidates = []
    fold_coverages = {}
    for result in selection["results"]:
        candidate = result["candidate"]
        if candidate != candidate_plan[candidate["name"]]:
            raise ValueError("Candidate parameters differ from selection plan")
        folds = []
        for fold in result["folds"]:
            specification = fold_plan[fold["name"]]
            start = _HOUR.validate_python(specification["cutoff"])
            end = _HOUR.validate_python(specification["end"])
            if end + timedelta(hours=48) > first_issue:
                raise ValueError("Development target period overlaps January comparison")
            comparison = fold["comparison"]["catboost"]
            metrics = _metrics(comparison["metrics"])
            baseline = _metrics(fold["comparison"]["persistence"]["metrics"])
            coverage = _coverage(metrics)
            if coverage != _coverage(baseline):
                raise ValueError("Development baselines require matching scored cells")
            if fold["name"] in fold_coverages and fold_coverages[fold["name"]] != coverage:
                raise ValueError("Candidates require identical development coverage")
            fold_coverages[fold["name"]] = coverage
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
        or min(candidates, key=lambda c: (c.pooled.mae, c.pooled.rmse)) != selected[0]
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
    if _HOUR.validate_python(refit["trained_through"]) <= last_issue:
        raise ValueError("Refit and evaluated model boundaries are inconsistent")
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
        refit={
            "trained_through": refit["trained_through"],
            "training_rows": refit["training_rows"],
        },
        checkpoints=[
            {
                "id": "chronology",
                "status": "verified",
                "title": "Chronological selection recorded",
                "detail": "Four planned candidates use November and December development folds. January was reused for comparison after selection; it is not an untouched test.",
            },
            {
                "id": "comparability",
                "status": "verified",
                "title": "Matched comparison coverage",
                "detail": f"All three models report the same {scored_pairs:,} scored issue/target pairs, grouped by turbine and horizon. Overlapping pairs are correlated.",
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
        + [
            "This endpoint presents a committed experiment summary; it does not run a new evaluation or verify local model deployment.",
            "MAE and RMSE are normalized-power errors on [0,1], not accuracy percentages or energy/money savings.",
            "The selected candidate does not win November MAE or pooled development RMSE; selection minimizes pooled development MAE.",
            "Two development folds and a reused January comparison do not establish general superiority across seasons. No calibrated uncertainty or significance claim is available.",
            "The experiment uses SCADA features only. Demo weather in its integration smoke check is not weather-forecast accuracy evidence.",
        ],
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
