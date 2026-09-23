import json
from datetime import datetime, timezone

import pandas as pd

from windagent import settings as S
from windagent import weather


def test_archive_merges_new_cached_run_even_when_csv_has_more_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "WEATHER_DIR", tmp_path)
    monkeypatch.setattr(S, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(weather, "_ARCHIVE", {})
    pd.DataFrame([
        {"run_utc": "2026-01-01 00:00", "loc": 1, "valid_utc": "2026-01-01 01:00", "wind_speed_100m": 1, "lead_h": 1},
        {"run_utc": "2026-01-02 00:00", "loc": 1, "valid_utc": "2026-01-02 01:00", "wind_speed_100m": 2, "lead_h": 1},
    ]).to_csv(tmp_path / "ecmwf_ifs_single_runs.csv", index=False)
    cache = tmp_path / "cache/single_runs/ecmwf_ifs"
    cache.mkdir(parents=True)
    (cache / "2026010300.json").write_text(json.dumps({"hourly": {"time": ["2026-01-03T01:00"], "wind_speed_100m": [3]}}))
    result = weather.load_archive()
    assert len(result) == 3 and result.run_utc.nunique() == 3
    assert weather.load_single_run(datetime(2026, 1, 1, tzinfo=timezone.utc), offline=True).wind_speed_100m.iloc[0] == 1


def test_secondary_weather_selects_requested_location():
    valid = pd.Series(pd.date_range("2026-01-02", periods=2, freq="1h"))
    rows = pd.DataFrame({"loc": [1, 1, 2, 2], "valid_utc": list(valid) * 2,
                         "wind_speed_80m_previous_day2": [1, 1, 9, 9]})
    result = weather.second_model_as_of(rows, pd.Timestamp("2026-01-01"), valid, loc=2)
    assert result.wind_speed_80m.tolist() == [9, 9]
