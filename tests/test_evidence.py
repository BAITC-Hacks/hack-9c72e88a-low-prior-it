import hashlib
import json
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
    assert report.benchmark.scored_pairs == 2688
    assert report.benchmark.unscored_pairs == 0
    assert report.data.complete_hours == 48452
    assert report.data.provisional is True
    assert report.refit.evaluated is False
    assert report.refit.trained_through > report.benchmark.trained_through
    models = {model.id: model for model in report.benchmark.models}
    assert models["selected"].pooled.mae == pytest.approx(0.2800609888392857)
    assert models["persistence"].pooled.mae == pytest.approx(0.3435974702380952)
    assert all(metric.samples == 672 for metric in models["selected"].metrics)
    assert sum(c.selected for c in report.selection.candidates) == 1
    assert report.source_sha256 == hashlib.sha256(evidence.EVIDENCE_PATH.read_bytes()).hexdigest()
    assert report.source_file == "model-selection-results.json"
    assert {s.source_file for s in report.data.sources} == {"turbine1.csv", "turbine2.csv"}
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
        payload["january"]["comparison"]["selected"]["pooled"]["mae"] = 0.01
    elif corruption == "coverage":
        payload["january"]["unscored_points"] = 1
    elif corruption == "future_fit":
        payload["january"]["training_request"]["last_origin"] = "2026-01-02T00:00:00Z"
    elif corruption == "selection":
        payload["selection"]["selected"] = payload["selection"]["plan"]["candidates"][0]
    else:
        payload["refit"]["evaluation"] = {"mae": 0.01}
    path = tmp_path / "corrupted-evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(evidence, "EVIDENCE_PATH", path)
    response = client.get("/api/v1/evidence")
    assert response.status_code == 503
    assert response.json()["code"] == "evidence_unavailable"
