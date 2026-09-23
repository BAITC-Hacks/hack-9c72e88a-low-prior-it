from datetime import timedelta
from pathlib import Path
from statistics import median

import pytest
from wind_backend.catboost_model import CatBoostPower, SnapshotIndex
from wind_backend.ml import PersistencePredictor
from wind_backend.weather_experiment import (
    FIRST_ORIGIN,
    JANUARY_CUTOFF,
    REFIT_CUTOFF,
    WEATHER_CANDIDATES,
    TrainingBaselines,
    _request,
    evaluate_comparison,
    training_implementation_digest,
    weather_input_digest,
)
from wind_contracts.models import ForecastRequest, WeatherSnapshot

from tests.test_catboost import BASE, TURBINE, observations, request, weather


def snapshot(turbine_id, origin=BASE, hours=48):
    return WeatherSnapshot(
        id=f"fixture-{turbine_id}",
        turbine_id=turbine_id,
        source="external-archive",
        weather_model="unit-test-only",
        run_init=origin - timedelta(hours=12),
        available_at=origin,
        retrieved_at=origin + timedelta(days=100),
        verification="verified",
        availability_evidence="Synthetic unit-test fixture, no operational provenance claim",
        wind_height_m=100,
        points=weather(origin, hours),
    )


def test_weather_training_skips_only_missing_archives_and_reports_origins():
    # Only the first of two training origins is covered. Training remains usable.
    snapshots = [snapshot(turbine) for turbine in ("turbine-1", "turbine-2")]
    model = CatBoostPower.fit(
        "model-weather", observations(), request(feature_set="weather-scada"), snapshots
    )
    assert model.info.training_rows == 96
    for report in model.report["turbines"].values():
        assert report["training_samples"] == 48
        assert report["skipped_origins_no_weather"] == 1
        assert report["origins_without_weather"] == [(BASE + timedelta(days=1)).isoformat()]
        assert len(report["weather_lineage"]) == 1
    # The same missing weather stays an error during inference/evaluation.
    issue = BASE + timedelta(hours=96)
    query = ForecastRequest(turbine_ids=[TURBINE.id], issued_at=issue, weather_source="archive")
    with pytest.raises(ValueError, match="eligible complete weather"):
        SnapshotIndex(snapshots).select(TURBINE, query)
    with pytest.raises(ValueError, match="match every prediction target"):
        model.predict_targets(TURBINE, [issue + timedelta(hours=1)], issue)
    with pytest.raises(ValueError, match="eligible complete weather"):
        evaluate_comparison(observations(), {"catboost": model}, issue, issue, snapshots)


def test_snapshot_index_preserves_publication_coverage_and_tie_break_rules():
    older = snapshot(TURBINE.id, hours=72)
    newer = older.model_copy(update={"id": "newer", "run_init": BASE - timedelta(hours=6)})
    late = newer.model_copy(update={"id": "late", "available_at": BASE + timedelta(seconds=1)})
    future = newer.model_copy(update={"id": "future", "run_init": BASE + timedelta(hours=1)})
    incomplete = newer.model_copy(update={"id": "missing", "points": newer.points[:-30]})
    wrong = older.model_copy(update={"id": "wrong", "turbine_id": "turbine-2"})
    index = SnapshotIndex([future, older, newer, late, incomplete, wrong])
    query = ForecastRequest(turbine_ids=[TURBINE.id], issued_at=BASE, weather_source="archive")
    assert index.select(TURBINE, query).id == "newer"


def test_baseline_statistics_exclude_future_and_late_labels():
    rows = observations()
    model = TrainingBaselines(rows, BASE)
    usable = [row for row in rows if row.valid_time <= BASE and row.available_at <= BASE]
    assert model.constant == median(row.power_normalized for row in usable)
    changed = [
        row.model_copy(update={"power_normalized": 1.0}) if row.available_at > BASE else row
        for row in rows
    ]
    assert TrainingBaselines(changed, BASE).report() == model.report()
    targets = [BASE + timedelta(hours=1), BASE + timedelta(hours=25)]
    output = model.predict_targets(TURBINE, targets, BASE, "climatology")
    assert output[0].power_normalized == output[1].power_normalized
    with pytest.raises(ValueError, match="cutoff"):
        model.predict_targets(TURBINE, targets, BASE - timedelta(hours=1), "constant")


def test_shared_pairs_include_issue_time_and_identical_missing_actuals():
    rows = observations()
    model = PersistencePredictor.fit("model-p", "dataset-p", rows, BASE)
    baselines = TrainingBaselines(rows, BASE)
    comparison, exports = evaluate_comparison(
        rows,
        {"persistence": model},
        BASE + timedelta(hours=96),
        BASE + timedelta(hours=120),
        baselines=baselines,
    )
    assert set(comparison) == {"persistence", "constant", "climatology"}
    assert len({entry["scored_pairs_sha256"] for entry in comparison.values()}) == 1
    assert len({entry["scored_points"] for entry in comparison.values()}) == 1
    assert all(entry["unscored_points"] == 48 for entry in comparison.values())
    assert len(exports) == 2 * 2 * 48 * 3
    earlier, _ = evaluate_comparison(
        rows, {"persistence": model}, BASE, BASE + timedelta(hours=24), baselines=baselines
    )
    assert (
        earlier["constant"]["scored_pairs_sha256"] != comparison["constant"]["scored_pairs_sha256"]
    )


def test_fixed_weather_training_clock_and_cutoffs():
    for cutoff in (JANUARY_CUTOFF, REFIT_CUTOFF):
        trained = _request("dataset-test", cutoff, WEATHER_CANDIDATES[0])
        assert trained.first_origin == FIRST_ORIGIN
        assert trained.last_origin.hour == 12
        assert trained.last_origin + timedelta(hours=48) <= cutoff
        assert trained.weather_source == "archive"
        assert trained.random_seed == 42


def test_weather_model_identity_ignores_only_local_import_clock():
    original = snapshot(TURBINE.id)
    expected = weather_input_digest([original])
    reimported = original.model_copy(
        update={
            "retrieved_at": original.retrieved_at + timedelta(days=1),
        }
    )
    assert weather_input_digest([reimported]) == expected
    changes = [
        {"available_at": original.available_at + timedelta(minutes=1)},
        {"source": "open-meteo-single-run"},
        {
            "points": [original.points[0].model_copy(update={"wind_speed_ms": 9})]
            + original.points[1:]
        },
    ]
    for change in changes:
        assert weather_input_digest([original.model_copy(update=change)]) != expected


def test_training_cache_fingerprint_changes_when_feature_code_changes(monkeypatch):
    original = training_implementation_digest()
    assert len(original) == 64
    assert training_implementation_digest() == original
    read_text = Path.read_text

    def changed_feature(path, *args, **kwargs):
        text = read_text(path, *args, **kwargs)
        return text + "\n# changed feature logic\n" if path.name == "features.py" else text

    monkeypatch.setattr(Path, "read_text", changed_feature)
    assert training_implementation_digest() != original
