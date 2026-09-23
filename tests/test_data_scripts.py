"""Exercise incoming CLI helpers against the integrated API and scoring contracts."""

import csv
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import httpx
import pandas as pd
import pytest

from scripts import import_weather_archive

from .conftest import ROOT, snapshot


def test_bundled_import_remains_unverified_and_accepts_existing_revision(
    client, monkeypatch, capsys
):
    archive = pd.DataFrame(
        {
            "run_utc": pd.to_datetime(["2026-01-30"] * 2),
            "loc": [1, 1],
            "valid_utc": pd.to_datetime(["2026-01-30T01:00", "2026-01-30T02:00"]),
            "wind_speed_100m": [8, None],
            "wind_direction_100m": [90, 90],
            "temperature_2m": [-5, -5],
        }
    )
    monkeypatch.setattr(import_weather_archive, "load_archive", lambda: archive)
    monkeypatch.setattr(sys, "argv", ["import_weather_archive.py"])
    real_client = httpx.Client

    def handler(request):
        response = client.post(request.url.path, json=json.loads(request.content))
        return httpx.Response(response.status_code, json=response.json())

    monkeypatch.setattr(
        import_weather_archive.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    import_weather_archive.main()
    assert "Imported 1 UNVERIFIED" in capsys.readouterr().out
    imported = client.get("/api/v1/weather/snapshots").json()
    assert len(imported) == 1
    assert imported[0]["verification"] == "unverified"
    assert imported[0]["available_at"] is None
    assert len(imported[0]["points"]) == 1
    import_weather_archive.main()
    assert "Imported 0 UNVERIFIED" in capsys.readouterr().out


@pytest.mark.parametrize("verified", [False, True])
def test_monthly_validation_reports_coverage_without_future_inputs(tmp_path, verified):
    data = tmp_path / "observations.csv"
    # A later measurement exists, but is unavailable throughout the replay.
    rows = [
        ("2025-10-29T00:00:00Z", "2025-10-29T00:00:00Z", 0.25),
        ("2025-10-29T01:00:00Z", "2025-12-01T00:00:00Z", 0.99),
        ("2025-11-01T08:00:00Z", "2025-11-01T08:00:00Z", 0.25),
    ]
    with data.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "turbine_id",
                "valid_time",
                "available_at",
                "wind_speed_ms",
                "temperature_c",
                "power_normalized",
            ]
        )
        for valid, available, power in rows:
            writer.writerow(["turbine-1", valid, available, 8, -5, power])
    issue = datetime(2025, 10, 31, 7, tzinfo=UTC)
    weather = snapshot(
        run_init=issue - timedelta(hours=12),
        available_at=issue,
        verification="verified" if verified else "unverified",
        points=[
            point.model_copy(update={"valid_time": issue + timedelta(hours=i)})
            for i, point in enumerate(snapshot().points, start=1)
        ],
    )
    weather_path = tmp_path / "weather.json"
    weather_path.write_text(json.dumps([weather.model_dump(mode="json")]), encoding="utf-8")
    output = tmp_path / "validation.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_models.py",
            "--data",
            str(data),
            "--snapshots",
            str(weather_path),
            "--months",
            "2025-11",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))["months"]["2025-11"]
    assert report["coverage"]["persistence"]["scored_points"] == 2
    assert all(metric["mae"] == 0 for metric in report["metrics"]["persistence"])
    assert report["coverage"]["binned-power-curve"]["scored_points"] == (2 if verified else 0)
    assert report["missing_weather_issue_turbine_pairs"]["binned-power-curve"] > 0
    assert "weather-ridge" in report["unavailable"]
    assert report["coverage"]["persistence"]["unscored_points"] > 0
