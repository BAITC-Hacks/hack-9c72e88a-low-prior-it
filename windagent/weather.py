"""Погодные данные в табличном виде: запуски моделей -> pandas.

Слой над openmeteo.py: превращает ответы API в DataFrame, собирает архив
для обучения и выдаёт прогноз, доступный на заданный момент времени.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import openmeteo as om
from . import settings as S


def run_to_frame(locs: list[dict], run_utc: datetime) -> pd.DataFrame:
    frames = []
    for i, loc in enumerate(locs):
        times, series = om.parse_hourly(loc)
        if not times:
            continue
        df = pd.DataFrame(series)
        df.insert(0, "valid_utc", pd.to_datetime([t.replace(tzinfo=None) for t in times]))
        df.insert(0, "loc", i + 1)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    run_naive = pd.Timestamp(run_utc.replace(tzinfo=None))
    out.insert(0, "run_utc", run_naive)
    out["lead_h"] = (out["valid_utc"] - run_naive) / pd.Timedelta(hours=1)
    for c in out.columns:
        if c not in ("run_utc", "valid_utc", "loc"):
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


_ARCHIVE: dict[str, pd.DataFrame] = {}


def _compiled_path(model: str, kind: str = "single_runs") -> Path | None:
    for ext in (".csv", ".csv.gz"):
        p = S.WEATHER_DIR / f"{model}_{kind}{ext}"
        if p.exists():
            return p
    return None


def _compiled_archive(model: str) -> pd.DataFrame | None:
    if model not in _ARCHIVE:
        p = _compiled_path(model)
        _ARCHIVE[model] = pd.read_csv(p, parse_dates=["run_utc", "valid_utc"]) if p else pd.DataFrame()
    df = _ARCHIVE[model]
    return None if df.empty else df


def load_single_run(run_utc: datetime, model: str = S.NWP_MODEL, offline: bool = False,
                    refresh: bool = False) -> pd.DataFrame:
    """Прогноз одного запуска: кэш ответа API -> локальный архив в репозитории -> Open-Meteo.

    offline=True запрещает сеть; refresh=True заново скачивает запуск из API.
    """
    lats, lons = S.turbine_coords()
    if not refresh:
        path = om.single_run_cache_path(S.CACHE_DIR, model, run_utc)
        if not path.exists():
            arch = _compiled_archive(model)
            if arch is not None:
                sel = arch[arch["run_utc"] == pd.Timestamp(run_utc.replace(tzinfo=None))]
                if len(sel):
                    return sel.reset_index(drop=True)
    locs = om.fetch_single_run(run_utc, lats, lons, S.CACHE_DIR, model=model, offline=offline,
                               use_cache=not refresh)
    return run_to_frame(locs, run_utc)


def load_archive(model: str = S.NWP_MODEL) -> pd.DataFrame:
    """Все запуски модели (для обучения): собранный CSV из репозитория + JSON-кэш."""
    cache = S.CACHE_DIR / "single_runs" / model
    arch = _compiled_archive(model)
    files = sorted(cache.glob("*.json"))
    if arch is not None and not files:
        return arch.copy()
    frames = [arch.copy()] if arch is not None else []
    for p in files:
        run = datetime.strptime(p.stem, "%Y%m%d%H").replace(tzinfo=timezone.utc)
        locs = om._as_list(json.loads(p.read_text(encoding="utf-8")))
        frames.append(run_to_frame(locs, run))
    if not frames:
        raise FileNotFoundError(
            f"Нет архива прогнозов в {cache}. Запустите: python scripts/fetch_weather.py")
    return pd.concat(frames, ignore_index=True).drop_duplicates(["run_utc", "loc", "valid_utc"], keep="last").sort_values(["run_utc", "loc", "valid_utc"]).reset_index(drop=True)


def load_previous_runs(model: str) -> pd.DataFrame:
    """Архив второй модели из Previous Runs API (суффиксы _previous_dayN)."""
    p = _compiled_path(model, "previous_runs")
    if p is not None:
        return pd.read_csv(p, parse_dates=["valid_utc"])
    cache = S.CACHE_DIR / "previous_runs" / model
    frames = []
    for p in sorted(cache.glob("*.json")) if cache.exists() else []:
        locs = om._as_list(json.loads(p.read_text(encoding="utf-8")))
        for i, loc in enumerate(locs):
            times, series = om.parse_hourly(loc)
            df = pd.DataFrame(series)
            df.insert(0, "valid_utc", pd.to_datetime([t.replace(tzinfo=None) for t in times]))
            df.insert(0, "loc", i + 1)
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True).drop_duplicates(["loc", "valid_utc"], keep="last")
    for c in out.columns:
        if c not in ("valid_utc", "loc"):
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def second_model_as_of(prev: pd.DataFrame, issue_utc: pd.Timestamp,
                       valid_utc: pd.Series, delay_h: float = S.NWP_PUBLISH_DELAY_H,
                       loc: int = 1) -> pd.DataFrame:
    """Значения второй модели, доступные на момент выпуска, без заглядывания в будущее.

    Для целевого часа T значение _previous_dayK получено запуском не позже T-24K ч.
    Берём наименьшее K, при котором этот запуск уже опубликован к issue_utc:
    T - 24K + delay <= issue  =>  K >= (T + delay - issue) / 24.
    """
    base = sorted({c.rsplit("_previous_day", 1)[0] for c in prev.columns if "_previous_day" in c})
    ks = sorted({int(c.rsplit("_previous_day", 1)[1]) for c in prev.columns if "_previous_day" in c})
    lead_days = np.ceil(((valid_utc - issue_utc) / pd.Timedelta(hours=1) + delay_h) / 24.0).clip(lower=1)
    rows = prev.set_index(["loc", "valid_utc"])
    out = {}
    for v in base:
        vals = np.full(len(valid_utc), np.nan)
        for k in ks:
            col = f"{v}_previous_day{k}"
            if col not in rows.columns:
                continue
            sel = (lead_days.to_numpy() == k)
            if sel.any():
                vals[sel] = rows[col].reindex(list(zip([loc] * sel.sum(), valid_utc[sel]))).to_numpy()
        out[v] = vals
    return pd.DataFrame(out, index=valid_utc.index)


def available_runs(issue_utc: datetime, model: str = S.NWP_MODEL,
                   delay_h: float = S.NWP_PUBLISH_DELAY_H, lookback: int = 4) -> list[datetime]:
    """Запуски, опубликованные к моменту issue_utc, от самого свежего к старым."""
    latest = om.latest_available_run(issue_utc, delay_h, S.NWP_CYCLE_H)
    return [latest - timedelta(hours=S.NWP_CYCLE_H * i) for i in range(lookback)]
