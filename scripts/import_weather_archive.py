"""Import bundled ECMWF rows as unverified candidates, never as historical proof."""
import argparse
from datetime import datetime, timezone

import httpx

from windagent.weather import load_archive
from wind_contracts import WeatherPoint, WeatherSnapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-01-29")
    parser.add_argument("--end", default="2026-03-01", help="Exclusive initialization date")
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    args = parser.parse_args()
    archive = load_archive()
    selected = archive[(archive.run_utc >= args.start) & (archive.run_utc < args.end)]
    count = 0
    with httpx.Client(timeout=60) as client:
        for (run, loc), rows in selected.groupby(["run_utc", "loc"]):
            points = [WeatherPoint(valid_time=r.valid_utc.tz_localize("UTC"), wind_speed_ms=r.wind_speed_100m,
                temperature_c=r.temperature_2m, wind_direction_deg=r.wind_direction_100m)
                for r in rows.dropna(subset=["wind_speed_100m", "temperature_2m", "wind_direction_100m"]).itertuples()]
            if not points:
                continue
            snapshot = WeatherSnapshot(id=f"bundled-ecmwf-{int(loc)}-{run:%Y%m%d%H}", turbine_id=f"turbine-{int(loc)}",
                source="Bundled data/weather/ecmwf_ifs_single_runs.csv.gz; original retrieval/publication evidence unavailable",
                weather_model="ecmwf_ifs", run_init=run.tz_localize("UTC"), retrieved_at=datetime.now(timezone.utc),
                wind_height_m=100, points=points,
                preparation="Imported from compiled CSV; retrieved_at is local import time. Null hours omitted. Lineage unverified.")
            response = client.post(f"{args.api}/weather/snapshots", json=snapshot.model_dump(mode="json"))
            if response.status_code != 409:
                response.raise_for_status()
                count += 1
    print(f"Imported {count} UNVERIFIED candidates; these cannot be used in archive replay.")


if __name__ == "__main__":
    main()
