"""Reproduction caches never replace immutable data or bypass model checksums."""

import csv
from copy import deepcopy
from datetime import timedelta

import pytest
from wind_backend.catboost_model import CatBoostPower
from wind_backend.storage import Repository

from scripts import reproduce
from tests.test_catboost import TURBINE, observations, request
from tests.test_weather_experiment import snapshot


def test_reimport_preserves_first_retrieval_and_rejects_weather_changes(tmp_path):
    repository = Repository(tmp_path / "fixture.sqlite3")
    original = snapshot(TURBINE.id)
    first = original.model_dump(mode="json")
    reproduce.put_immutable(repository, "weather", original.id, first)
    later = original.model_copy(
        update={
            "retrieved_at": original.retrieved_at + timedelta(days=1),
        }
    ).model_dump(mode="json")
    reproduce.put_immutable(repository, "weather", original.id, later)
    assert repository.get("weather", original.id) == first
    changed_point = deepcopy(later)
    changed_point["points"][0]["wind_speed_ms"] += 1
    changed_availability = deepcopy(later)
    changed_availability["available_at"] = (original.available_at + timedelta(hours=1)).isoformat()
    for changed in (changed_point, changed_availability):
        with pytest.raises(ValueError, match="different immutable weather"):
            reproduce.put_immutable(repository, "weather", original.id, changed)
        assert repository.get("weather", original.id) == first


@pytest.mark.parametrize("filename", ["observations.csv", "preparation.json"])
def test_prepared_cache_checks_checksum_before_reuse(tmp_path, monkeypatch, filename):
    directory = tmp_path / "canonical"
    directory.mkdir()
    rows = observations()[:2]
    with (directory / "observations.csv").open("w", encoding="utf-8", newline="") as stream:
        records = [row.model_dump(mode="json") for row in rows]
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    preparation = {"provisional": True}
    reproduce.write_json(directory / "preparation.json", preparation)
    reproduce.write_json(
        tmp_path / "canonical-checksums.json",
        {
            name: reproduce.sha256(directory / name)
            for name in ("observations.csv", "preparation.json")
        },
    )

    def must_not_prepare(*args, **kwargs):
        raise AssertionError("Existing immutable cache must not be silently rebuilt")

    monkeypatch.setattr(reproduce.subprocess, "run", must_not_prepare)
    assert reproduce.prepare(tmp_path) == (rows, preparation)
    path = directory / filename
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="Canonical input checksum mismatch"):
        reproduce.prepare(tmp_path)


@pytest.mark.parametrize("tamper", ["report", "history", "weights"])
def test_experiment_reuse_checks_report_history_and_weights(tmp_path, monkeypatch, tamper):
    rows = observations()
    model = CatBoostPower.fit("model-cache-fixture", rows, request())
    model_root = tmp_path / "models"
    artifact = model.save(model_root)
    report = {"fixture": "Only cache-loading behavior is under test"}
    path = tmp_path / "experiment.json"
    reproduce.write_json(
        path,
        {
            "report": report,
            "january_artifact": artifact,
            "refit_artifact": artifact,
        },
    )
    reproduce.write_json(
        tmp_path / "experiment-checksum.json",
        {
            "sha256": reproduce.sha256(path),
        },
    )

    def must_not_train(*args, **kwargs):
        raise AssertionError("Cache checks must not fall back to unrequested retraining")

    monkeypatch.setattr(reproduce, "run_weather_experiment", must_not_train)
    loaded_report, january, refit, loaded_artifact = reproduce.experiment(
        tmp_path,
        rows,
        [],
        {"provisional": True},
        "dataset-test",
    )
    assert loaded_report == report and loaded_artifact == artifact
    assert january.info == model.info == refit.info
    if tamper == "report":
        path.write_bytes(path.read_bytes() + b"\n")
        expected = "Cached experiment checksum mismatch"
    elif tamper == "history":
        rows = rows[:-1]
        expected = "history checksum mismatch"
    else:
        weights = model_root / model.info.id / "turbine-1.cbm"
        weights.write_bytes(weights.read_bytes() + b"corrupt")
        expected = "artifact path or checksum mismatch"
    with pytest.raises(ValueError, match=expected):
        reproduce.experiment(tmp_path, rows, [], {"provisional": True}, "dataset-test")
