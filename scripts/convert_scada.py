"""Convert case SCADA to interval-end UTC. Preserve real stoppages in the target."""
import argparse
import json
from pathlib import Path

import pandas as pd

from windagent import settings as S
from windagent.scada import load_turbine_10min


def convert(latency_minutes: float):
    if latency_minutes < 0:
        raise ValueError("latency must be nonnegative")
    frames, report = [], {}
    for t in S.TURBINES:
        raw = load_turbine_10min(t["file"])
        # Valid actual output includes stoppages/curtailment. Do not fit any curve
        # to the full dataset or discard low-power outcomes before validation.
        valid = raw[["ws", "p", "temp"]].notna().all(axis=1) & raw.p.between(0, 1)
        clean = raw.where(valid)
        group = clean.resample("1h")
        hourly = group.mean()
        hourly = hourly[group.p.count() >= 4].dropna()
        end = (hourly.index - pd.Timedelta(hours=6) + pd.Timedelta(hours=1)).tz_localize("UTC")
        out = pd.DataFrame({"turbine_id": f"turbine-{t['id']}", "valid_time": end,
            "available_at": end + pd.Timedelta(minutes=latency_minutes), "wind_speed_ms": hourly.ws.to_numpy(),
            "temperature_c": hourly.temp.to_numpy(), "power_normalized": hourly.p.to_numpy()})
        frames.append(out)
        report[str(t["id"])] = {"raw_rows": len(raw), "excluded_invalid_rows": int((~valid).sum()),
            "canonical_hours": len(out), "start": end.min().isoformat(), "end": end.max().isoformat()}
    return pd.concat(frames, ignore_index=True), report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latency-minutes", type=float, required=True,
                        help="Explicit assumed/confirmed observation latency after interval end")
    parser.add_argument("--output", type=Path, default=Path("data/canonical/observations.csv"))
    args = parser.parse_args()
    frame, report = convert(args.latency_minutes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False)
    metadata = {"source": "Supplied SCADA; coordinate/normalization confirmation from project owner",
        "timezone": "Fixed UTC+6, inferred from SCADA/weather correlation; accepted by project owner",
        "timing": "10-minute source treated as interval-start samples; hourly mean relabelled at interval end",
        "latency_minutes": args.latency_minutes, "latency_status": "explicit caller assumption; not confirmed by case",
        "target": "Normalized actual power; stoppages preserved; at least 4 valid samples/hour; no clipping",
        "turbines": report}
    args.output.with_suffix(".metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
