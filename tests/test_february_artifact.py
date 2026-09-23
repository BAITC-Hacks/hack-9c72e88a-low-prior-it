"""Audit the committed forecast itself, not only a mocked prediction path."""

import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results/february-2026"


def test_committed_february_reconstruction_has_complete_available_bounded_forecasts():
    manifest = json.loads((RESULTS / "manifest.json").read_text(encoding="utf-8"))
    csv_path = RESULTS / "forecast.csv"
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == manifest["forecast_sha256"]
    assert manifest["weather_source"] == "archive"
    assert manifest["synthetic_weather"] is False
    assert manifest["operational_historical_availability_proven"] is False
    assert manifest["metrics"] == [] and manifest["scored_points"] == 0
    assert manifest["model"]["algorithm"] == "catboost-weather-scada-v1"
    assert manifest["issue_count"] == 29 and manifest["horizon_hours"] == 48
    for name, checksum in manifest["input_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == checksum
    with csv_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == manifest["forecast_rows"] == 29 * 2 * 48
    cutoff = datetime.fromisoformat(manifest["model"]["trained_through"])
    first, last = (datetime.fromisoformat(manifest[key]) for key in ("first_issue", "last_issue"))
    groups = defaultdict(list)
    for row in rows:
        issue, valid, run, available = (
            datetime.fromisoformat(row[key])
            for key in ("issue_time", "valid_time", "run_init", "available_at")
        )
        assert all(moment.utcoffset() == timedelta(0) for moment in (issue, valid, run, available))
        assert cutoff <= issue and run <= available <= issue
        assert available - run == timedelta(hours=manifest["weather"]["publication_delay_hours"])
        assert issue.hour == 12 and run.hour == 0 and issue.date() == run.date()
        assert valid == issue + timedelta(hours=int(row["lead_hours"]))
        assert 0 <= float(row["power_normalized"]) <= 1
        assert row["model_id"] == manifest["model"]["id"]
        lineage = manifest["snapshots"][row["snapshot_id"]]
        assert lineage["turbine_id"] == row["turbine_id"]
        assert lineage["run_init"] == row["run_init"]
        assert lineage["available_at"] == row["available_at"]
        groups[issue, row["turbine_id"]].append(int(row["lead_hours"]))
    expected_issues = {first + timedelta(days=day) for day in range(29)}
    assert max(expected_issues) == last
    assert set(groups) == {
        (issue, turbine) for issue in expected_issues for turbine in manifest["turbine_ids"]
    }
    assert all(sorted(leads) == list(range(1, 49)) for leads in groups.values())
