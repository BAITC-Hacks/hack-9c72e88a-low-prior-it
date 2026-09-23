"""Reproduce the weather experiment and February reconstruction from bundled inputs."""

import argparse
import asyncio
import csv
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from wind_agent.ecmwf_archive import import_ecmwf_archive
from wind_backend.catboost_model import CatBoostPower, history_digest
from wind_backend.config import Settings
from wind_backend.features import ObservationHistory
from wind_backend.service import WindService
from wind_backend.storage import Repository
from wind_backend.weather_experiment import run_weather_experiment
from wind_contracts.models import (
    BacktestRequest,
    BacktestRun,
    DatasetInfo,
    DatasetUpload,
    ForecastRun,
    Observation,
    WeatherSnapshot,
)

ROOT = Path(__file__).resolve().parents[1]
INPUTS = (
    "data/raw/turbine_1.csv",
    "data/raw/turbine_2.csv",
    "data/weather/ecmwf_ifs_single_runs.csv.gz",
)
FIRST_ISSUE = datetime(2026, 1, 31, 12, tzinfo=UTC)
LAST_ISSUE = datetime(2026, 2, 28, 12, tzinfo=UTC)
PROTOCOL = "ecmwf-00z-noon-48h-v1"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )


def identity():
    inputs = {name: sha256(ROOT / name) for name in INPUTS}
    implementation = {
        str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path)
        for folder in ("agent/wind_agent", "backend/wind_backend", "contracts/wind_contracts")
        for path in sorted((ROOT / folder).glob("*.py"))
    }
    for name in ("scripts/prepare_dataset.py", "scripts/reproduce.py", "uv.lock"):
        implementation[name] = sha256(ROOT / name)
    key = hashlib.sha256(json.dumps([PROTOCOL, inputs, implementation], sort_keys=True).encode())
    return key.hexdigest(), inputs, implementation


def prepare(work):
    prepared = work / "canonical"
    integrity = work / "canonical-checksums.json"
    if not integrity.exists():
        subprocess.run(
            [
                sys.executable,
                "scripts/prepare_dataset.py",
                "--input-dir",
                "data/raw",
                "--filename-pattern",
                "turbine_{number}.csv",
                "--output",
                str(prepared),
                "--timezone",
                "UTC+06:00",
                "--timestamp-position",
                "start",
                "--latency-minutes",
                "10",
                "--provisional",
                "--time-semantics-confirmed",
                "--quarantine-invalid",
            ],
            cwd=ROOT,
            check=True,
        )
        write_json(
            integrity,
            {name: sha256(prepared / name) for name in ("observations.csv", "preparation.json")},
        )
    for name, digest in json.loads(integrity.read_text(encoding="utf-8")).items():
        if sha256(prepared / name) != digest:
            raise ValueError(f"Canonical input checksum mismatch: {name}")
    with (prepared / "observations.csv").open(encoding="utf-8", newline="") as stream:
        rows = [Observation.model_validate(row) for row in csv.DictReader(stream)]
    return rows, json.loads((prepared / "preparation.json").read_text(encoding="utf-8"))


def archive(work):
    path = work / "weather.json"
    if not path.exists():
        imported = import_ecmwf_archive(
            ROOT / INPUTS[2],
            accept_schedule_assumption=True,
        )
        write_json(
            path,
            {
                "metadata": imported.metadata,
                "snapshots": [s.model_dump(mode="json") for s in imported.snapshots],
            },
        )
        write_json(work / "weather-checksum.json", {"sha256": sha256(path)})
    expected = json.loads((work / "weather-checksum.json").read_text(encoding="utf-8"))
    if sha256(path) != expected["sha256"]:
        raise ValueError("Cached immutable weather checksum mismatch")
    saved = json.loads(path.read_text(encoding="utf-8"))
    return [WeatherSnapshot.model_validate(s) for s in saved["snapshots"]], saved["metadata"]


def put_immutable(repository, kind, identifier, value):
    existing = repository.get(kind, identifier)
    if kind == "weather" and existing is not None:
        # A repeat import does not replace the first recorded retrieval time.
        # Every weather value and availability/provenance field must still match.
        def semantic(record):
            return {key: entry for key, entry in record.items() if key != "retrieved_at"}

        if semantic(existing) == semantic(value):
            return
    if existing is not None and existing != value:
        raise ValueError(f"Refusing to replace different immutable {kind}: {identifier}")
    if existing is None:
        repository.put(kind, identifier, value)


def register_dataset(repository, rows, dataset_id):
    payload = DatasetUpload(
        name="Organizer SCADA / reproducible weather experiment",
        is_demo=True,
        provenance=(
            "Bundled organizer CSV; fixed UTC+06:00 interval starts; "
            "10-minute latency assumed; normalized power, unknown rated capacity."
        ),
        observations=rows,
    )
    info = DatasetInfo(
        id=dataset_id,
        name=payload.name,
        is_demo=payload.is_demo,
        provenance=payload.provenance,
        rows=len(rows),
        first_time=min(r.valid_time for r in rows),
        last_time=max(r.valid_time for r in rows),
    )
    put_immutable(
        repository,
        "dataset",
        dataset_id,
        {"info": info.model_dump(mode="json"), "data": payload.model_dump(mode="json")},
    )


def experiment(work, rows, snapshots, preparation, dataset_id):
    path = work / "experiment.json"
    model_root = work / "models"
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        expected = json.loads((work / "experiment-checksum.json").read_text(encoding="utf-8"))
        if sha256(path) != expected["sha256"]:
            raise ValueError("Cached experiment checksum mismatch")
        models = [
            CatBoostPower.load(cached[key], model_root, rows)
            for key in ("january_artifact", "refit_artifact")
        ]
        print("Reusing completed, checksum-validated experiment.", flush=True)
        return cached["report"], models[0], models[1], cached["refit_artifact"]
    training_cache = ROOT / "artifacts" / "reproduce-models"
    report, january, refit = run_weather_experiment(
        rows,
        snapshots,
        preparation,
        dataset_id,
        cache_root=training_cache,
    )
    for model in (january, refit):
        source = training_cache / model.info.id
        destination = model_root / model.info.id
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination)
    january_artifact = json.loads(
        (model_root / january.info.id / "manifest.json").read_text(encoding="utf-8")
    )
    refit_artifact = json.loads(
        (model_root / refit.info.id / "manifest.json").read_text(encoding="utf-8")
    )
    january = CatBoostPower.load(january_artifact, model_root, rows)
    refit = CatBoostPower.load(refit_artifact, model_root, rows)
    write_json(
        path,
        {"report": report, "january_artifact": january_artifact, "refit_artifact": refit_artifact},
    )
    write_json(work / "experiment-checksum.json", {"sha256": sha256(path)})
    return report, january, refit, refit_artifact


async def replay(service, model_id, output):
    replay_id = "backtest-reproduce-february-2026"
    saved = service.repository.get("backtest", replay_id)
    if saved is None or saved["status"] != "succeeded":
        request = BacktestRequest(
            turbine_ids=sorted(service.turbines),
            issued_at=FIRST_ISSUE,
            last_issued_at=LAST_ISSUE,
            horizon_hours=48,
            weather_source="archive",
            model_id=model_id,
            evaluation_start=datetime(2026, 2, 1, tzinfo=UTC),
            evaluation_end=datetime(2026, 3, 1, tzinfo=UTC),
            actuals_dataset_id=None,
        )
        run = BacktestRun(
            id=replay_id,
            created_at=datetime.now(UTC),
            status="queued",
            request=request,
            is_demo=True,
        )
        service.validate_request(request)
        service.save_backtest(run)
        await service.execute_backtest(run.id)
    run = BacktestRun.model_validate(service.required("backtest", replay_id))
    if run.status != "succeeded":
        raise RuntimeError(f"February archive replay failed: {run.error}")
    if run.scored_points or run.metrics:
        raise ValueError("February has no actuals: metrics must remain empty")
    records, lineages = [], {}
    for run_id in run.forecast_ids:
        child = ForecastRun.model_validate(service.required("forecast", run_id))
        if child.status != "succeeded" or child.result is None:
            raise ValueError("Replay contains an incomplete forecast")
        by_turbine = {s.turbine_id: s for s in child.result.snapshots}
        for point in child.result.points:
            snapshot = by_turbine[point.turbine_id]
            records.append(
                {
                    "issue_time": child.request.issued_at.isoformat(),
                    "turbine_id": point.turbine_id,
                    "valid_time": point.valid_time.isoformat(),
                    "lead_hours": point.lead_hours,
                    "power_normalized": point.power_normalized,
                    "model_id": child.result.model_id,
                    "snapshot_id": snapshot.id,
                    "run_init": snapshot.run_init.isoformat(),
                    "available_at": snapshot.available_at.isoformat(),
                }
            )
            lineages[snapshot.id] = {
                "turbine_id": snapshot.turbine_id,
                "run_init": snapshot.run_init.isoformat(),
                "available_at": snapshot.available_at.isoformat(),
                "retrieved_at": snapshot.retrieved_at.isoformat(),
                "sha256": hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest(),
                "availability_evidence": snapshot.availability_evidence,
            }
    records.sort(key=lambda r: (r["issue_time"], r["turbine_id"], r["valid_time"]))
    output.mkdir(parents=True, exist_ok=True)
    with (output / "forecast.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    return run, records, lineages


def publish(work, rows, dataset_id, snapshots, artifact):
    # No cloud calls: registration only. Respect the same local DB/model settings as the API.
    settings = Settings.from_env()
    repository = Repository(settings.db_path)
    register_dataset(repository, rows, dataset_id)
    identifier = artifact["info"]["id"]
    destination = settings.models_path / identifier
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(work / "models" / identifier, destination)
    CatBoostPower.load(artifact, settings.models_path, rows)
    put_immutable(repository, "model", identifier, artifact)
    for snapshot in snapshots:
        put_immutable(repository, "weather", snapshot.id, snapshot.model_dump(mode="json"))
    print(f"Registered {identifier} and {len(snapshots)} archive snapshots for the dashboard.")


def print_metrics(report):
    print("\nJanuary / identical issue-target pairs / normalized power")
    print(f"{'Model':20} {'N':>6} {'MAE':>10} {'RMSE':>10}")
    for name, comparison in report["january"]["comparison"].items():
        score = comparison["pooled"]
        print(f"{name:20} {score['samples']:6} {score['mae']:10.6f} {score['rmse']:10.6f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-register", action="store_true", help="Do not publish into API registry"
    )
    args = parser.parse_args()
    started = time.monotonic()
    key, inputs, implementation = identity()
    work = ROOT / "artifacts" / "reproduce" / key[:16]
    work.mkdir(parents=True, exist_ok=True)
    output = ROOT / "results" / "february-2026"
    print(f"Protocol {PROTOCOL}; cache {work.relative_to(ROOT)}", flush=True)
    print(
        "HINDCAST reconstruction: 10h publication delay is assumed, not per-run proof.", flush=True
    )
    canonical_key = hashlib.sha256(
        json.dumps(
            {
                "inputs": {
                    name: digest for name, digest in inputs.items() if name.endswith(".csv")
                },
                "implementation": {
                    name: digest
                    for name, digest in implementation.items()
                    if name
                    in (
                        "scripts/prepare_dataset.py",
                        "agent/wind_agent/scada.py",
                        "agent/wind_agent/source_data.py",
                        "contracts/wind_contracts/scada.py",
                        "contracts/wind_contracts/models.py",
                    )
                },
                "timezone": "UTC+06:00",
                "position": "start",
                "latency_minutes": 10,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:16]
    canonical_cache = ROOT / "data" / "canonical" / canonical_key
    canonical_cache.mkdir(parents=True, exist_ok=True)
    rows, preparation = prepare(canonical_cache)
    archive_key = (
        inputs[INPUTS[2]][:16] + "-" + implementation["agent/wind_agent/ecmwf_archive.py"][:16]
    )
    archive_cache = ROOT / "artifacts" / "reproduce-weather" / archive_key
    archive_cache.mkdir(parents=True, exist_ok=True)
    snapshots, weather_metadata = archive(archive_cache)
    history_sha = history_digest(ObservationHistory(rows))
    dataset_id = f"dataset-weather-{history_sha[:20]}"
    report, _, refit, artifact = experiment(work, rows, snapshots, preparation, dataset_id)
    report["weather"] = weather_metadata
    repository = Repository(work / "replay.sqlite3")
    register_dataset(repository, rows, dataset_id)
    put_immutable(repository, "model", refit.info.id, artifact)
    february = [
        s for s in snapshots if FIRST_ISSUE.date() <= s.run_init.date() <= LAST_ISSUE.date()
    ]
    for snapshot in february:
        put_immutable(repository, "weather", snapshot.id, snapshot.model_dump(mode="json"))
    turbines = Settings(
        db_path=work / "replay.sqlite3", turbines_path=ROOT / "config/turbines.example.json"
    ).turbines()
    service = WindService(repository, turbines, work / "models")
    print(
        "Running 29 daily 48h archive forecasts through WindService / ForecastAgent...", flush=True
    )
    replay_run, records, lineage = asyncio.run(replay(service, refit.info.id, output))
    manifest = {
        "protocol": PROTOCOL,
        "status": "provisional-hindcast-reconstruction",
        "weather_source": "archive",
        "synthetic_weather": False,
        "operational_historical_availability_proven": False,
        "model": refit.info.model_dump(mode="json"),
        "parameters": refit.report["parameters"],
        "model_files": artifact["models"],
        "history_sha256": history_sha,
        "input_sha256": inputs,
        "implementation_sha256": implementation,
        "versions": {
            "python": platform.python_version(),
            **{name: version(name) for name in ("catboost", "numpy", "pandas", "pydantic")},
        },
        "first_issue": FIRST_ISSUE.isoformat(),
        "last_issue": LAST_ISSUE.isoformat(),
        "issue_hour_utc": 12,
        "issue_time_local": "17:00 Asia/Almaty (UTC+05:00 in February 2026)",
        "issue_step_hours": 24,
        "horizon_hours": 48,
        "turbine_ids": sorted(service.turbines),
        "issue_count": len(replay_run.forecast_ids),
        "forecast_rows": len(records),
        "forecast_sha256": sha256(output / "forecast.csv"),
        "weather": weather_metadata,
        "snapshots": lineage,
        "scored_points": 0,
        "metrics": [],
        "february_target_pairs": replay_run.unscored_points,
        "target_policy": "UTC interval ends; full T+1..T+48 retained, including edge dates",
        "scada_assumptions": {
            key: preparation[key]
            for key in (
                "timezone",
                "timestamp_position",
                "latency_minutes",
                "provisional",
                "normalization",
            )
        },
        "limitations": [
            *weather_metadata.get("limitations", []),
            "February actual generation was not supplied; no February accuracy is claimed.",
            "SCADA latency is assumed to be 10 minutes; rated capacity and hub height are unknown.",
            "After January observations end, SCADA history ages without synthetic updates.",
            "January is a reused comparison period, not a previously untouched holdout.",
        ],
    }
    write_json(output / "manifest.json", manifest)
    report["february"] = {
        "forecast": "results/february-2026/forecast.csv",
        "manifest": "results/february-2026/manifest.json",
        "rows": len(records),
        "metrics": [],
        "weather_source": "archive",
    }
    write_json(ROOT / "docs/model-selection-results.json", report)
    (output / "README.md").write_text(
        "# February 2026 forecast reconstruction\n\n"
        "`forecast.csv` contains 29 daily issues (31 January–28 February, 12:00 UTC / "
        "17:00 Asia/Almaty), two turbines and 48 hourly targets per turbine: 2,784 rows. "
        "All horizon rows are retained, including January/March boundary targets.\n\n"
        "The refitted CatBoost weather-SCADA model runs through the same "
        "`WindService.execute_backtest` / `ForecastAgent` path as the API. "
        "Weather comes exclusively from bundled ECMWF 00 UTC runs, with 100 m wind. "
        "No synthetic weather or February observed power is used.\n\n"
        "**Provisional hindcast reconstruction, not proven historical operational availability.** "
        "Publication is assumed at run initialization + 10 hours. Open-Meteo documents "
        "early ECMWF runs as IFS 49R1 hindcasts; the published dissemination schedule "
        "does not prove availability of each archived run. See "
        "[provenance](../../docs/weather-archive.md).\n\n"
        "`manifest.json` records checksums, model parameters, versions, each selected snapshot "
        "and assumptions. Power is a normalized fraction [0,1], not MW. "
        "February actuals are unavailable: metrics are intentionally empty.\n\n"
        "Rebuild from the repository root with `npm run reproduce`. "
        "Verify with `uv run python scripts/run_tests.py`.\n",
        encoding="utf-8",
    )
    if not args.no_register:
        publish(work, rows, dataset_id, february, artifact)
    print_metrics(report)
    elapsed = time.monotonic() - started
    print(f"\nCompleted in {elapsed:.1f}s; {len(records)} rows in {output.relative_to(ROOT)}")
    print("February accuracy: unavailable (no actuals). Hindcast availability remains provisional.")


if __name__ == "__main__":
    main()
