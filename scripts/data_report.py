"""Reproduce local data coverage and timezone-correlation evidence without network."""
import json
from pathlib import Path

import pandas as pd

from windagent import settings as S
from windagent.scada import flag_anomalies, load_all_hourly, load_turbine_10min
from windagent.weather import load_archive


def main():
    report = {"scada": {}, "weather": {}}
    for turbine in S.TURBINES:
        raw = load_turbine_10min(turbine["file"])
        expected = len(pd.date_range(raw.index.min(), raw.index.max(), freq="10min"))
        gaps = raw.index.to_series().diff()
        report["scada"][turbine["name"]] = {"rows": len(raw), "expected": expected,
            "missing_fraction": 1 - len(raw) / expected, "gaps_over_2h": int((gaps > pd.Timedelta(hours=2)).sum()),
            "longest_gap": str(gaps.max()), "invalid_values": raw.isna().sum().to_dict(),
            "simple_anomaly_fraction": float(flag_anomalies(raw).mean())}
    for path in sorted(S.WEATHER_DIR.glob("*.csv.gz")):
        data = pd.read_csv(path)
        report["weather"][path.name] = {"rows": len(data), "missing_fraction": data.isna().mean().to_dict()}
    long, curves = load_all_hourly()
    archive = load_archive()
    wind = archive[(archive["loc"] == 1) & (archive.lead_h < 24)].drop_duplicates("valid_utc").set_index("valid_utc").wind_speed_100m.sort_index()
    mid = (wind + wind.shift(-1)) / 2
    scada = long.groupby("time_local").ws.mean()
    report["wind_timezone_correlations"] = {}
    for year in (2024, 2025):
        report["wind_timezone_correlations"][str(year)] = {}
        for offset in (4, 5, 6, 7, 8):
            candidate = scada.copy()
            candidate.index -= pd.Timedelta(hours=offset)
            joined = pd.concat([candidate, mid], axis=1, join="inner").dropna()
            joined = joined[joined.index.year == year]
            report["wind_timezone_correlations"][str(year)][str(offset)] = float(joined.iloc[:, 0].corr(joined.iloc[:, 1]))
    report["power_curve_samples"] = {str(k): c.predict([3, 5, 7, 9, 11, 13, 20]).tolist() for k, c in curves.items()}
    report["notes"] = ["Archive coverage does not prove historical availability.",
                       "Legacy curve filtering is exploratory; canonical actuals preserve curtailment."]
    path = Path("artifacts/data-report.json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
