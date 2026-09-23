"""End-to-end HTTP demo, using Vite proxy by default. Not a predictive accuracy test."""
import argparse
import csv
import io
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:5173/api/v1")
    args = parser.parse_args()
    with httpx.Client(base_url=args.api, timeout=60) as client:
        def post(path, body):
            response = client.post(path, json=body)
            response.raise_for_status()
            return response.json()

        def poll(path):
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                response = client.get(path)
                response.raise_for_status()
                value = response.json()
                if value["status"] in ("succeeded", "failed"):
                    assert value["status"] == "succeeded", value.get("error")
                    return value
                time.sleep(.2)
            raise TimeoutError(path)

        root = Path(__file__).resolve().parents[1]
        with (root / "examples/observations.demo.csv").open(encoding="utf-8") as file:
            rows = list(csv.DictReader(file))
        dataset = post("/datasets", {"name": "smoke-artificial", "demo": True, "provenance": "Artificial smoke integration data", "observations": rows})
        model = post("/models/train", {"dataset_id": dataset["id"], "trained_through": "2026-01-30T23:00:00Z"})
        request = {"turbine_ids": ["turbine-1", "turbine-2"], "issued_at": "2026-01-31T00:00:00Z",
                   "horizon_hours": 48, "weather_source": "demo", "model_id": model["id"]}
        run = post("/forecasts", request)
        result = poll(f"/forecasts/{run['id']}")
        assert len(result["result"]["points"]) == 96 and result["result"]["demo"]
        assert post(f"/forecasts/{run['id']}/refresh", {})["id"] == run["id"]
        replay = post("/backtests", {**request, "end_issue_at": "2026-02-28T00:00:00Z",
            "evaluation_start": "2026-02-01T00:00:00Z", "evaluation_end": "2026-03-01T00:00:00Z"})
        replay = poll(f"/backtests/{replay['id']}")
        assert replay["completed"] == 29
        assert all(m["mae"] is None for m in replay["metrics"])
        export = client.get(f"/backtests/{replay['id']}/export")
        export.raise_for_status()
        values = list(csv.DictReader(io.StringIO(export.text)))
        assert all("2026-02-01" <= r["valid_time"] < "2026-03-01" for r in values)
        out = root / "artifacts"
        out.mkdir(exist_ok=True)
        (out / "february-demo.csv").write_text(export.text, encoding="utf-8")
        (out / "february-demo-report.json").write_text(__import__("json").dumps(replay, indent=2), encoding="utf-8")
        print(f"PASS: import, training, 96 forecast points, refresh reuse, 29 daily issues, {len(values)} exported demo rows")


if __name__ == "__main__":
    main()
