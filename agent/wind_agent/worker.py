"""Refresh watcher, with an optional bounded candidate-acquisition cycle."""

import argparse
import json
import math
import time
from datetime import UTC, datetime, timedelta

import httpx
from wind_contracts.models import ForecastRun, RefreshResponse, WeatherFetchRequest, WeatherSnapshot


def utc_hour(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Use an explicit UTC hour, for example 2026-01-31T00:00:00Z"
        ) from exc
    if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
        raise argparse.ArgumentTypeError(
            "Weather initialization requires explicit UTC (Z or +00:00)"
        )
    if moment.minute or moment.second or moment.microsecond:
        raise argparse.ArgumentTypeError("Weather initialization must be a whole UTC hour")
    return moment.astimezone(UTC)


def run_cycle(client: httpx.Client, run_id: str, *, fetch_run_init: datetime | None = None) -> dict:
    """Make bounded API calls; acquisition never grants historical verification.

    A completed cycle means the API accepted the refresh check, not that a newly
    queued forecast has completed. Failed acquisition stops before refresh and
    retains already-downloaded candidate IDs in the report.
    """
    report = {
        "cycle_status": "failed",
        "source_run_id": run_id,
        "candidates": [],
        "refresh": None,
        "error": None,
    }
    stage = "load_run" if fetch_run_init is not None else "refresh"
    turbine_id = None
    try:
        if fetch_run_init is not None:
            response = client.get(f"/api/v1/forecasts/{run_id}")
            response.raise_for_status()
            original = ForecastRun.model_validate(response.json())
            if original.id != run_id or original.status != "succeeded" or original.result is None:
                raise ValueError("Candidate acquisition requires the selected successful forecast")
            fetch = WeatherFetchRequest(
                turbine_id=original.request.turbine_ids[0], run_init=fetch_run_init
            )
            if fetch.run_init > original.request.issued_at:
                raise ValueError(
                    "Weather initialization is later than the selected forecast issue time"
                )
            stage = "fetch_weather"
            for turbine_id in original.request.turbine_ids:
                fetch = WeatherFetchRequest(turbine_id=turbine_id, run_init=fetch_run_init)
                response = client.post("/api/v1/weather/fetch", json=fetch.model_dump(mode="json"))
                response.raise_for_status()
                candidate = WeatherSnapshot.model_validate(response.json())
                record = {
                    "id": candidate.id,
                    "turbine_id": candidate.turbine_id,
                    "run_init": candidate.run_init.isoformat(),
                    "verification": candidate.verification,
                    "available_at": candidate.available_at.isoformat()
                    if candidate.available_at
                    else None,
                    "accepted_as_unverified_candidate": False,
                }
                report["candidates"].append(record)
                if (
                    candidate.turbine_id != turbine_id
                    or candidate.run_init != fetch.run_init
                    or candidate.weather_model != fetch.weather_model
                    or candidate.source != "open-meteo-single-run"
                    or candidate.verification != "unverified"
                    or candidate.available_at is not None
                    or candidate.availability_evidence
                ):
                    raise ValueError(
                        "Candidate does not match the requested run/turbine or claims publication "
                        "evidence. Acquisition must return unverified weather without availability; "
                        "the worker will not verify or use it."
                    )
                record["accepted_as_unverified_candidate"] = True
            report["acquisition_note"] = (
                "Candidates remain unverified; no publication time was inferred. "
                "Archive refresh can select only independently verified eligible snapshots; "
                "demo refresh keeps synthetic weather."
            )
        stage, turbine_id = "refresh", None
        response = client.post(f"/api/v1/forecasts/{run_id}/refresh")
        response.raise_for_status()
        refreshed = RefreshResponse.model_validate(response.json())
        report["refresh"] = {
            "changed": refreshed.changed,
            "run_id": refreshed.run.id,
            "forecast_status": refreshed.run.status,
            "weather_source": refreshed.run.request.weather_source,
        }
        if refreshed.run.status == "failed":
            raise ValueError(refreshed.run.error or "Refreshed forecast failed")
        report["cycle_status"] = "completed"
    except (httpx.HTTPError, ValueError) as exc:
        report["error"] = {"stage": stage, "turbine_id": turbine_id, "message": str(exc)}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Recompute a forecast when its stored inputs change"
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one cycle and print a JSON report; do not wait for a queued forecast",
    )
    parser.add_argument(
        "--fetch-run-init",
        type=utc_hour,
        help="Download unverified candidates for this explicit UTC cycle before refresh; requires --once",
    )
    args = parser.parse_args(argv)
    if not math.isfinite(args.interval) or args.interval < 5:
        parser.error("interval must be at least 5 seconds")
    if args.fetch_run_init is not None and not args.once:
        parser.error(
            "--fetch-run-init requires --once to avoid repeated downloads of the same cycle"
        )
    run_id = args.run_id
    with httpx.Client(base_url=args.api, timeout=60) as client:
        if args.once:
            report = run_cycle(client, run_id, fetch_run_init=args.fetch_run_init)
            print(json.dumps(report, indent=2), flush=True)
            return 0 if report["cycle_status"] == "completed" else 1
        try:
            while True:
                report = run_cycle(client, run_id)
                if report["cycle_status"] == "completed":
                    refreshed = report["refresh"]
                    run_id = refreshed["run_id"]
                    print(f"changed={refreshed['changed']} run={run_id}", flush=True)
                else:
                    print(f"Refresh failed: {report['error']['message']}", flush=True)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
