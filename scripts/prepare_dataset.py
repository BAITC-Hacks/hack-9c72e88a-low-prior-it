"""Prepare organizer SCADA using explicit, recorded time/latency assumptions."""

import argparse
import csv
import json
from pathlib import Path

from wind_agent.scada import aggregate_hourly, profile_scada
from wind_agent.source_data import read_organizer_csv
from wind_contracts.models import Observation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("dataset"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--timestamp-position", choices=["start", "end"], required=True)
    parser.add_argument("--latency-minutes", type=int, required=True)
    parser.add_argument(
        "--provisional", action="store_true", help="Time/normalization assumptions are unconfirmed"
    )
    parser.add_argument("--quarantine-invalid", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output directory already exists; choose a new revision path")
    all_hours, sources, profiles = [], [], {}
    for number in (1, 2):
        turbine = f"turbine-{number}"
        rows, source = read_organizer_csv(
            args.input_dir / f"turbine{number}.csv",
            turbine_id=turbine,
            timezone=args.timezone,
            timestamp_position=args.timestamp_position,
            latency_minutes=args.latency_minutes,
            quarantine_invalid=args.quarantine_invalid,
        )
        hours = aggregate_hourly(rows)
        sources.append(source)
        profiles.update(profile_scada(rows))
        profiles[turbine]["complete_hours"] = sum(hour.complete for hour in hours)
        profiles[turbine]["incomplete_hours"] = sum(not hour.complete for hour in hours)
        all_hours.extend(hours)
    args.output.mkdir(parents=True)
    with (args.output / "observations.csv").open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(Observation.model_fields))
        writer.writeheader()
        for hour in all_hours:
            if hour.complete:
                writer.writerow(hour.to_observation().model_dump(mode="json"))
    with (args.output / "hourly_statistics.jsonl").open("w", encoding="utf-8") as output:
        for hour in all_hours:
            output.write(hour.model_dump_json() + "\n")
    report = {
        "provisional": args.provisional,
        "timezone": args.timezone,
        "timestamp_position": args.timestamp_position,
        "latency_minutes": args.latency_minutes,
        "normalization": "source values unchanged; assumed capacity fraction [0,1]",
        "target_policy": "complete hours only; missing intervals are never zero-filled",
        "sources": sources,
        "profiles": profiles,
    }
    (args.output / "preparation.json").write_text(
        json.dumps(report, default=str, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {"output": str(args.output), "provisional": args.provisional, "profiles": profiles},
            default=str,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
