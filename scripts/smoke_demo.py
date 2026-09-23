"""Exercise the running API through either its direct URL or the Vite proxy."""

import argparse
import csv
import io
import time

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:5173")
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
            deadline = time.monotonic() + 60
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
        assert {model["id"] for model in evidence["benchmark"]["models"]} == {
            "selected",
            "previous",
            "persistence",
        }
        evidence_export = client.get("/api/v1/evidence/export")
        evidence_export.raise_for_status()
        assert evidence_export.json() == evidence
        assert "attachment" in evidence_export.headers["content-disposition"]
        turbines = get("/api/v1/turbines")
        payload = {
            "turbine_ids": [t["id"] for t in turbines],
            "issued_at": "2026-01-31T00:00:00Z",
            "horizon_hours": 48,
            "weather_source": "demo",
            "model_id": "demo-power-curve",
        }
        created = post("/api/v1/forecasts", payload)
        run = wait(f"/api/v1/forecasts/{created['id']}")
        assert run["result"]["is_demo"]
        assert len(run["result"]["points"]) == 48 * len(turbines)
        analysis = [event["message"] for event in run["events"] if event["stage"] == "analyse"]
        assert all(
            any(t["id"] in message and "peak" in message for message in analysis) for t in turbines
        )
        assert post(f"/api/v1/forecasts/{run['id']}/refresh", {})["changed"] is False

        replay_request = payload | {
            "last_issued_at": "2026-02-28T00:00:00Z",
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
        assert len(rows) == 1343 * len(turbines)
        assert all(row["is_demo"] == "True" for row in rows)
        print(f"PASS: health, {len(turbines)} turbines, 48-hour forecast, unchanged-input refresh")
        print("PASS: recorded model evidence, JSON download, per-turbine forecast analysis")
        print(f"PASS: 29 daily demo forecasts, {len(rows)} February issue/target pairs, CSV export")


if __name__ == "__main__":
    main()
