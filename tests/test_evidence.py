import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta
from math import sqrt

import pytest
from wind_backend import evidence
from wind_backend.service import WindService
from wind_contracts.evidence import EvidenceReport, EvidenceScore


def test_committed_evidence_is_read_only_and_downloadable(client, monkeypatch):
    def forbid_training(*args, **kwargs):
        pytest.fail("Reading evidence must not train a model")

    monkeypatch.setattr(WindService, "train", forbid_training)
    before = client.get("/api/v1/models").json()
    response = client.get("/api/v1/evidence")
    assert response.status_code == 200
    report = EvidenceReport.model_validate(response.json())
    assert report.status == "provisional"
    assert report.benchmark.reused_comparison is True
    source = json.loads(evidence.EVIDENCE_PATH.read_bytes())
    assert report.benchmark.scored_pairs > 0
    assert report.benchmark.unscored_pairs >= 0
    assert report.data.complete_hours == 48452
    assert report.data.provisional is True
    assert report.refit.evaluated is False
    assert report.refit.trained_through > report.benchmark.trained_through
    models = {model.id: model for model in report.benchmark.models}
    selected_id = source["january"].get("selected_model", "selected")
    assert models[selected_id].pooled.mae == pytest.approx(
        source["january"]["comparison"][selected_id]["pooled"]["mae"]
    )
    assert sum(model.selected for model in models.values()) == 1
    assert all(model.pooled.samples == report.benchmark.scored_pairs for model in models.values())
    if "weather_scada" in models:
        assert set(models) == {"constant", "climatology", "persistence", "scada", "weather_scada"}
        assert report.weather is not None
        assert len({model.scored_pairs_sha256 for model in models.values()}) == 1
    assert sum(c.selected for c in report.selection.candidates) == 1
    assert report.source_sha256 == hashlib.sha256(evidence.EVIDENCE_PATH.read_bytes()).hexdigest()
    assert report.source_file == "model-selection-results.json"
    assert len({s.source_file for s in report.data.sources}) == 2
    assert "artifacts" not in response.text
    assert "model-1ce904" not in response.text
    assert "untouched" in " ".join(c.detail for c in report.checkpoints)
    download = client.get("/api/v1/evidence/export")
    assert download.status_code == 200
    assert (
        download.headers["content-disposition"] == 'attachment; filename="wind-model-evidence.json"'
    )
    assert download.json() == response.json()
    assert client.get("/api/v1/models").json() == before
    assert client.get("/api/v1/datasets").json() == []


def test_pooling_weights_samples_and_squared_errors():
    score = evidence.pooled_score(
        [
            EvidenceScore(samples=1, mae=0.2, rmse=0.3),
            EvidenceScore(samples=3, mae=0.4, rmse=0.5),
        ]
    )
    assert score.samples == 4
    assert score.mae == pytest.approx(0.35)
    assert score.rmse == pytest.approx(sqrt((0.3**2 + 3 * 0.5**2) / 4))
    assert score.rmse != pytest.approx((0.3 + 3 * 0.5) / 4)


@pytest.mark.parametrize("endpoint", ["/api/v1/evidence", "/api/v1/evidence/export"])
@pytest.mark.parametrize("contents", [None, "not JSON", '{"selection": {}}'])
def test_missing_or_invalid_evidence_is_explicit(client, monkeypatch, tmp_path, endpoint, contents):
    path = tmp_path / "missing-or-invalid.json"
    if contents is not None:
        path.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(evidence, "EVIDENCE_PATH", path)
    response = client.get(endpoint)
    assert response.status_code == 503
    assert response.json()["code"] == "evidence_unavailable"
    assert str(tmp_path) not in response.text


@pytest.mark.parametrize(
    "corruption", ["aggregate", "coverage", "future_fit", "selection", "refit"]
)
def test_inconsistent_experiments_are_not_published(client, monkeypatch, tmp_path, corruption):
    payload = json.loads(evidence.EVIDENCE_PATH.read_bytes())
    if corruption == "aggregate":
        selected_id = payload["january"].get("selected_model", "selected")
        payload["january"]["comparison"][selected_id]["pooled"]["mae"] = 0.01
    elif corruption == "coverage":
        payload["january"]["unscored_points"] = 1
    elif corruption == "future_fit":
        payload["january"]["training_request"]["last_origin"] = "2026-01-02T00:00:00Z"
    elif corruption == "selection":
        payload["selection"]["selected"] = next(
            candidate for candidate in payload["selection"]["plan"]["candidates"]
            if candidate != payload["selection"]["selected"]
        )
    else:
        payload["refit"]["evaluation"] = {"mae": 0.01}
    path = tmp_path / "corrupted-evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(evidence, "EVIDENCE_PATH", path)
    response = client.get("/api/v1/evidence")
    assert response.status_code == 503
    assert response.json()["code"] == "evidence_unavailable"


@pytest.fixture
def weather_evidence():
    """Exercise the weather report contract independently of recorded model scores."""
    payload = json.loads(evidence.EVIDENCE_PATH.read_bytes())
    if "weather_scada" in payload["january"]["comparison"]:
        return payload
    january = payload["january"]
    comparison = january["comparison"]
    digest = "a" * 64
    january["comparison"] = {
        identifier: deepcopy(comparison["selected"])
        for identifier in ("constant", "climatology", "persistence", "scada", "weather_scada")
    }
    january["scored_pairs_sha256"] = digest
    january["selected_model"] = "weather_scada"
    january["baseline_training"] = {"cutoff": january["model"]["trained_through"]}
    january["scada_training_request"] = deepcopy(january["training_request"])
    january["scada_model"] = deepcopy(january["model"])
    for record in january["comparison"].values():
        record.update(
            scored_pairs_sha256=digest,
            scored_points=record["pooled"]["samples"],
            unscored_points=january["unscored_points"],
        )
    january["training_request"]["feature_set"] = "weather-scada"
    january["model"]["algorithm"] = "catboost-weather-scada-v1"
    payload["refit"]["request"]["feature_set"] = "weather-scada"
    for key in ("validation_start", "validation_end"):
        january[key] = (datetime.fromisoformat(january[key]) + timedelta(hours=12)).isoformat()
    selection = payload["selection"]
    selection["selected"]["feature_set"] = "weather-scada"
    for candidate in selection["plan"]["candidates"]:
        candidate["feature_set"] = "weather-scada"
    for fold in selection["plan"]["folds"]:
        fold["start"] = (datetime.fromisoformat(fold["cutoff"]) + timedelta(hours=12)).isoformat()
        fold["end"] = (datetime.fromisoformat(fold["end"]) + timedelta(hours=12)).isoformat()
    for result in selection["results"]:
        result["candidate"]["feature_set"] = "weather-scada"
        for fold in result["folds"]:
            for record in fold["comparison"].values():
                record["scored_pairs_sha256"] = digest
    payload["weather"] = {
        "source": "Test fixture archive", "model": "test-ecmwf", "source_sha256": "b" * 64,
        "run_hour_utc": 0, "issue_hour_utc": 12, "publication_delay_hours": 8,
        "availability_basis": "Fixture assumes schedule-based availability, not per-run evidence.",
        "limitations": ["Fixture provenance only; no real historical availability claim."],
    }
    return payload


def test_weather_evidence_exposes_all_baselines_and_provenance(weather_evidence):
    report = evidence._build_report(weather_evidence, "c" * 64)
    assert report.benchmark.feature_set == "weather-scada"
    assert [model.id for model in report.benchmark.models] == [
        "constant", "climatology", "persistence", "scada", "weather_scada",
    ]
    assert [model.id for model in report.benchmark.models if model.selected] == ["weather_scada"]
    assert report.weather.issue_hour_utc == 12
    assert report.weather.limitations[0] in report.limitations
    assert not any("uses SCADA features only" in note for note in report.limitations)


@pytest.mark.parametrize("corruption", [
    "january_pairs", "fold_pairs", "provenance", "publication", "issue_hour", "constant_missing",
    "checksum", "features", "baseline_future", "scada_future",
])
def test_weather_evidence_rejects_incomparable_or_unavailable_inputs(weather_evidence, corruption):
    if corruption == "january_pairs":
        weather_evidence["january"]["comparison"]["constant"]["scored_pairs_sha256"] = "d" * 64
    elif corruption == "fold_pairs":
        weather_evidence["selection"]["results"][0]["folds"][0]["comparison"]["catboost"]["scored_pairs_sha256"] = "d" * 64
    elif corruption == "provenance":
        del weather_evidence["weather"]
    elif corruption == "publication":
        weather_evidence["weather"]["publication_delay_hours"] = 13
    elif corruption == "issue_hour":
        weather_evidence["weather"]["issue_hour_utc"] = 11
    elif corruption == "constant_missing":
        del weather_evidence["january"]["comparison"]["constant"]
    elif corruption == "checksum":
        weather_evidence["weather"]["source_sha256"] = "not-a-sha256"
    elif corruption == "baseline_future":
        weather_evidence["january"]["baseline_training"]["cutoff"] = "2026-01-02T00:00:00Z"
    elif corruption == "scada_future":
        weather_evidence["january"]["scada_training_request"]["last_origin"] = "2026-01-02T00:00:00Z"
    else:
        weather_evidence["january"]["training_request"]["feature_set"] = "scada"
    with pytest.raises((ValueError, KeyError)):
        evidence._build_report(weather_evidence, "c" * 64)
