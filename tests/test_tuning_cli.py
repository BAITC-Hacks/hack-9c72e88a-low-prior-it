import json
import subprocess

import pytest

from scripts.tune_model import run_experiment


def test_resume_reuses_identical_completed_fold_and_rejects_changed_inputs(tmp_path, monkeypatch):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "preparation.json").write_text('{"provisional": true}', encoding="utf-8")
    output = tmp_path / "fold"
    calls = []

    def complete(command, **kwargs):
        calls.append(command)
        folder = output / "experiment-fixture"
        folder.mkdir()
        (folder / "report.json").write_text(
            json.dumps(
                dict(
                    preparation=dict(provisional=True),
                    model=dict(id="model-fixture"),
                    comparison={key: dict(scored_points=48) for key in ("catboost", "persistence")},
                )
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("scripts.tune_model.subprocess.run", complete)
    args = (
        prepared,
        output,
        dict(name="fixture", depth=2),
        "2025-11-01T00:00:00Z",
        "2025-11-14T00:00:00Z",
    )
    first = run_experiment(*args)
    assert run_experiment(*args, resume=True) == first
    assert len(calls) == 1
    with pytest.raises(ValueError, match="identical command"):
        run_experiment(prepared, output, dict(name="fixture", depth=4), *args[3:], resume=True)
    (prepared / "preparation.json").write_text('{"provisional": false}', encoding="utf-8")
    with pytest.raises(ValueError, match="revision changed"):
        run_experiment(*args, resume=True)


def test_failed_fold_keeps_log_and_can_be_retried(tmp_path, monkeypatch):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "preparation.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "fold"

    def fail(command, stdout, **kwargs):
        stdout.write("interrupted training")
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr("scripts.tune_model.subprocess.run", fail)
    args = (prepared, output, dict(name="fixture"), "2025-11-01T00:00:00Z", "2025-11-14T00:00:00Z")
    for resume in (False, True):
        with pytest.raises(subprocess.CalledProcessError):
            run_experiment(*args, resume=resume)
    assert (output / "console.log").read_text(encoding="utf-8") == "interrupted training"
    assert len(list(output.glob("console-retry-*.log"))) == 1
