"""Exercise the running API through either its direct URL or the Vite proxy."""

import argparse
import csv
import io
import time
from datetime import datetime, timedelta

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:5173")
    parser.add_argument(
        "--archive", action="store_true",
        help="Use the registered weather-SCADA refit and imported archive after reproduce",
    )
    args = parser.parse_args()

    with httpx.Client(base_url=args.api, timeout=30) as client:

        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        def post(path, payload):
            response = client.post(path, json=payload)
            response.raise_for_status()
            return response.json()

        def wait(path):
            deadline = time.monotonic() + (180 if args.archive else 60)
            while time.monotonic() < deadline:
                run = get(path)
                if run["status"] == "failed":
                    raise RuntimeError(run["error"])
                if run["status"] == "succeeded":
                    return run
                time.sleep(0.25)
            raise TimeoutError(f"Job did not finish: {path}")

        assert get("/health")["status"] == "ok"
        evidence = get("/api/v1/evidence")
        assert evidence["status"] == "provisional"
        identifiers = {model["id"] for model in evidence["benchmark"]["models"]}
        assert identifiers in (
            {"constant", "climatology", "persistence", "scada", "weather_scada"},
            {"selected", "previous", "persistence"},
        )
        if args.archive:
            assert "weather_scada" in identifiers and evidence["weather"] is not None
            assert len({model["scored_pairs_sha256"] for model in evidence["benchmark"]["models"]}) == 1
        evidence_export = client.get("/api/v1/evidence/export")
        evidence_export.raise_for_status()
        assert evidence_export.json() == evidence
        assert "attachment" in evidence_export.headers["content-disposition"]
        turbines = get("/api/v1/turbines")
        issue_time = "2026-01-31T12:00:00Z"
        last_issue = "2026-02-28T12:00:00Z"
        model_id = "demo-power-curve"
        if args.archive:
            models = [
                model for model in get("/api/v1/models")
                if model["algorithm"] == "catboost-weather-scada-v1"
                and model["trained_through"] is not None
                and datetime.fromisoformat(model["trained_through"]) <= datetime.fromisoformat(issue_time)
                and {t["id"] for t in turbines} <= set(model["turbine_ids"])
            ]
            if not models:
                raise RuntimeError("No eligible weather-SCADA model; run npm run reproduce first")
            model_id = max(models, key=lambda model: model["trained_through"])["id"]
        payload = {
            "turbine_ids": [t["id"] for t in turbines],
            "issued_at": issue_time,
            "horizon_hours": 48,
            "weather_source": "archive" if args.archive else "demo",
            "model_id": model_id,
        }
        created = post("/api/v1/forecasts", payload)
        run = wait(f"/api/v1/forecasts/{created['id']}")
        if args.archive:
            assert run["result"]["model_id"] == model_id
            for snapshot in run["result"]["snapshots"]:
                assert snapshot["source"] != "demo" and snapshot["verification"] == "verified"
                assert datetime.fromisoformat(snapshot["run_init"]) <= datetime.fromisoformat(issue_time)
                assert datetime.fromisoformat(snapshot["available_at"]) <= datetime.fromisoformat(issue_time)
        else:
            assert run["result"]["is_demo"]
        assert len(run["result"]["points"]) == 48 * len(turbines)
        analysis = [event["message"] for event in run["events"] if event["stage"] == "analyse"]
        assert all(
            any(t["id"] in message and "peak" in message for message in analysis) for t in turbines
        )
        assert post(f"/api/v1/forecasts/{run['id']}/refresh", {})["changed"] is False

        replay_request = payload | {
            "last_issued_at": last_issue,
            "evaluation_start": "2026-02-01T00:00:00Z",
            "evaluation_end": "2026-03-01T00:00:00Z",
        }
        created_replay = post("/api/v1/backtests", replay_request)
        replay = wait(f"/api/v1/backtests/{created_replay['id']}")
        assert len(replay["forecast_ids"]) == 29
        assert replay["scored_points"] == 0 and replay["metrics"] == []
        response = client.get(f"/api/v1/backtests/{replay['id']}/export")
        response.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(response.text)))
        first = datetime.fromisoformat(issue_time)
        evaluation_start = datetime.fromisoformat(replay_request["evaluation_start"])
        evaluation_end = datetime.fromisoformat(replay_request["evaluation_end"])
        expected_pairs = sum(
            evaluation_start <= first + timedelta(days=day, hours=lead) < evaluation_end
            for day in range(29) for lead in range(1, 49)
        ) * len(turbines)
        assert len(rows) == expected_pairs
        if not args.archive:
            assert all(row["is_demo"] == "True" for row in rows)
        print(f"PASS: health, {len(turbines)} turbines, 48-hour forecast, unchanged-input refresh")
        print("PASS: recorded model evidence, JSON download, per-turbine forecast analysis")
        mode = "archive" if args.archive else "demo"
        print(f"PASS: 29 daily {mode} forecasts, {len(rows)} February issue/target pairs, CSV export")


if __name__ == "__main__":
    main()
