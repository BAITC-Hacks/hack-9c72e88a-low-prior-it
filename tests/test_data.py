"""Тесты слоя данных: SCADA, кривая мощности, архив погоды и правила «на момент прогноза».

Сеть не нужна: используются файлы из data/raw и data/weather.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from windagent import openmeteo as om  # noqa: E402
from windagent import settings as S  # noqa: E402
from windagent import weather  # noqa: E402
from windagent.scada import (  # noqa: E402
    PowerCurve,
    farm_hourly,
    load_all_hourly,
    load_turbine_10min,
)


@pytest.fixture(scope="module")
def scada():
    long, curves = load_all_hourly()
    return long, curves, farm_hourly(long)


def test_raw_files_and_period():
    for t in S.TURBINES:
        df = load_turbine_10min(t["file"])
        assert df.index.min() == pd.Timestamp("2023-03-11 00:00")
        assert df.index.max() == pd.Timestamp("2026-01-31 23:50")
        assert df.index.is_monotonic_increasing and not df.index.duplicated().any()


def test_scada_hourly_is_clean(scada):
    long, _, farm = scada
    assert set(long["turbine"].unique()) == {1, 2}
    assert long["p"].dropna().between(0, 1.05).all()
    assert farm["farm"].notna().sum() > 20000
    # шкала SCADA = UTC+6
    assert (
        (long["time_local"] - long["time_utc"]).eq(pd.Timedelta(hours=S.SCADA_UTC_OFFSET_H)).all()
    )


def test_power_curve_monotone(scada):
    _, curves, _ = scada
    for c in curves.values():
        v = c.predict(np.linspace(0, 25, 200))
        assert np.all(np.diff(v) >= -1e-12)
        assert 0.9 < v[-1] <= 1.0
        assert c.predict([2.0])[0] < 0.05


def test_expected_power_smooths_curve():
    ws = np.repeat(np.arange(0, 20, 0.1), 40)
    pc = PowerCurve().fit(ws, np.clip((ws - 3) / 9, 0, 1))
    assert pc.expected(np.array([12.0]), 2.0)[0] < pc.predict([12.0])[0]


def test_weather_archive_complete():
    nwp = weather.load_archive()
    runs = nwp["run_utc"].drop_duplicates()
    assert runs.min() == pd.Timestamp("2024-03-14 00:00")
    # все четыре запуска в сутки для тестового периода
    need = pd.date_range("2026-01-29", "2026-02-28 18:00", freq="6h")
    assert set(need) <= set(runs)
    assert nwp["wind_speed_100m"].notna().mean() > 0.99
    assert set(nwp["loc"].unique()) == {1, 2}


def test_latest_available_run_respects_publication_delay():
    # 07:00 UTC (12:00 Астаны): запуск 00 UTC уже опубликован (задержка 6 ч), 06 UTC - ещё нет
    issue = datetime(2026, 2, 10, 7, tzinfo=UTC)
    assert om.latest_available_run(issue, 6.0) == datetime(2026, 2, 10, 0, tzinfo=UTC)
    early = datetime(2026, 2, 10, 5, tzinfo=UTC)
    assert om.latest_available_run(early, 6.0) == datetime(2026, 2, 9, 18, tzinfo=UTC)
    runs = weather.available_runs(issue)
    assert all(r + pd.Timedelta(hours=S.NWP_PUBLISH_DELAY_H) <= issue for r in runs)


def test_second_model_no_leak():
    valid = pd.Series(pd.date_range("2026-01-15 18:00", periods=48, freq="1h"))
    prev = pd.DataFrame(
        {
            "loc": 1,
            "valid_utc": valid,
            "wind_speed_80m_previous_day1": 1.0,
            "wind_speed_80m_previous_day2": 2.0,
            "wind_speed_80m_previous_day3": 3.0,
        }
    )
    issue = pd.Timestamp("2026-01-15 07:00")
    k = weather.second_model_as_of(prev, issue, valid)["wind_speed_80m"].to_numpy()
    lead_h = ((valid - issue) / pd.Timedelta(hours=1)).to_numpy()
    # запуск, давший значение, стартовал не позже valid - 24k ч и был опубликован до выпуска
    assert np.all(lead_h - 24 * k + S.NWP_PUBLISH_DELAY_H <= 0)


def test_scada_time_scale_is_utc_plus_6(scada):
    """Корреляция ветра SCADA и ECMWF максимальна при сдвиге 6 ч."""
    long, _, _ = scada
    nwp = weather.load_archive()
    n = (
        nwp[(nwp["loc"] == 1) & (nwp["lead_h"] < 24)]
        .drop_duplicates("valid_utc")
        .set_index("valid_utc")
    )
    ws = n["wind_speed_100m"].sort_index()
    mid = (ws + ws.shift(-1)) / 2
    f = long.groupby("time_local")["ws"].mean()
    corr = {}
    for k in (4, 5, 6, 7, 8):
        s = f.copy()
        s.index = s.index - pd.Timedelta(hours=k)
        j = pd.concat([s, mid], axis=1, join="inner").dropna()
        corr[k] = j.iloc[:, 0].corr(j.iloc[:, 1])
    assert max(corr, key=corr.get) == 6
