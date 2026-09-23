"""Pre-February chronological validation, preserving each issue/valid/turbine pair.

Persistence works on canonical SCADA alone. Weather models require a JSON list
of verified snapshots; unavailable weather is reported, never replaced by demo.
"""

import argparse
import asyncio
import csv
import hashlib
import json
from bisect import bisect_right
from datetime import UTC, datetime, timedelta
from pathlib import Path

from wind_agent.interfaces import WeatherUnavailable
from wind_agent.weather import ArchiveWeatherProvider, target_hours
from wind_backend.evaluation import evaluate
from wind_backend.features import ObservationHistory
from wind_backend.ml import BinnedPowerCurve
from wind_backend.ridge_model import WeatherRidge
from wind_contracts.models import (
    ForecastPoint,
    ForecastRequest,
    Observation,
    TrainRequest,
    Turbine,
    WeatherSnapshot,
)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/canonical/observations.csv"))
    parser.add_argument(
        "--snapshots", type=Path, help="JSON list of independently verified WeatherSnapshot objects"
    )
    parser.add_argument("--months", nargs="+", default=["2025-10", "2025-11", "2025-12", "2026-01"])
    parser.add_argument("--issue-hour-utc", type=int, default=7)
    parser.add_argument("--output", type=Path, default=Path("artifacts/validation.json"))
    args = parser.parse_args()
    if not 0 <= args.issue_hour_utc <= 23:
        parser.error("issue hour must be in 0..23")
    with args.data.open(encoding="utf-8-sig", newline="") as stream:
        observations = ObservationHistory(
            [Observation.model_validate(r) for r in csv.DictReader(stream)]
        ).rows
    if not observations:
        parser.error("data must contain at least one observation")
    ids = sorted({r.turbine_id for r in observations})
    by_turbine = {
        tid: sorted([r for r in observations if r.turbine_id == tid], key=lambda r: r.valid_time)
        for tid in ids
    }
    indexes = {tid: [r.valid_time for r in rows] for tid, rows in by_turbine.items()}
    snapshots = (
        [
            WeatherSnapshot.model_validate(r)
            for r in json.loads(args.snapshots.read_text(encoding="utf-8"))
        ]
        if args.snapshots
        else []
    )
    provider = ArchiveWeatherProvider(lambda: snapshots)
    digest = hashlib.sha256(
        json.dumps([r.model_dump(mode="json") for r in observations], sort_keys=True).encode()
    ).hexdigest()
    report = {
        "data_fingerprint": digest,
        "issue_hour_utc": args.issue_hour_utc,
        "protocol": "UTC hourly interval ends; issue+1..48; chronological monthly training; end-exclusive evaluation",
        "notes": [
            "Capacity fractions, not MW. Observation latency follows the canonical CSV metadata.",
            "Persistence metrics do not require weather. Weather candidates require independently verified archive coverage.",
            "February is not used for selection; future curtailments remain unknown.",
        ],
        "months": {},
    }
    for month in args.months:
        start = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        if end > datetime(2026, 2, 1, tzinfo=UTC):
            parser.error("validation months must end before February 2026")
        first_issue = start - timedelta(days=2) + timedelta(hours=args.issue_hour_utc)
        cutoff = first_issue - timedelta(hours=1)
        predictors = {}
        unavailable = {}
        if snapshots:
            for name in ("binned-power-curve", "weather-ridge"):
                try:
                    if name == "binned-power-curve":
                        predictors[name] = BinnedPowerCurve.fit(
                            f"validation-{month}-curve", "canonical", observations, cutoff
                        )
                    else:
                        request = TrainRequest(
                            dataset_id="canonical", trained_through=cutoff, algorithm=name
                        )
                        predictors[name] = WeatherRidge.fit(
                            f"validation-{month}-ridge", observations, request, snapshots
                        )
                except ValueError as exc:
                    unavailable[name] = str(exc)
        else:
            unavailable = {
                name: "No verified snapshots supplied"
                for name in ("binned-power-curve", "weather-ridge")
            }
        predictions = {"persistence": [], **{name: [] for name in predictors}}
        skip = {name: 0 for name in predictors}
        missing_observations = 0
        issue = first_issue
        while issue < end:
            for tid in ids:
                candidates = by_turbine[tid][: bisect_right(indexes[tid], issue)]
                last = next((r for r in reversed(candidates) if r.available_at <= issue), None)
                if last:
                    for lead in range(1, 49):
                        valid = issue + timedelta(hours=lead)
                        if start <= valid < end:
                            predictions["persistence"].append(
                                ForecastPoint(
                                    turbine_id=tid,
                                    valid_time=valid,
                                    lead_hours=lead,
                                    power_normalized=last.power_normalized,
                                )
                            )
                else:
                    missing_observations += 1
                for name, predictor in predictors.items():
                    req = ForecastRequest(
                        turbine_ids=[tid],
                        issued_at=issue,
                        model_id=predictor.info.id,
                        weather_source="archive",
                    )
                    turbine = Turbine(id=tid, name=tid)
                    try:
                        weather = await provider.fetch(turbine, req)
                    except WeatherUnavailable:
                        skip[name] += 1
                        continue
                    targets = set(target_hours(req))
                    points = [point for point in weather.points if point.valid_time in targets]
                    predictions[name].extend(
                        p
                        for p in predictor.predict(turbine, points, issue)
                        if start <= p.valid_time < end
                    )
            issue += timedelta(days=1)
        scores = {name: evaluate(points, observations) for name, points in predictions.items()}
        report["months"][month] = {
            "trained_through": cutoff.isoformat(),
            "unavailable": unavailable,
            "missing_weather_issue_turbine_pairs": skip,
            "persistence_missing_observation_issue_turbine_pairs": missing_observations,
            "models": {
                name: predictor.info.model_dump(mode="json")
                for name, predictor in predictors.items()
            },
            "coverage": {
                name: {"scored_points": scored, "unscored_points": missing}
                for name, (_, scored, missing) in scores.items()
            },
            "metrics": {
                name: [m.model_dump() for m in metrics] for name, (metrics, _, _) in scores.items()
            },
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    asyncio.run(main())
