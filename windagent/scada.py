"""Загрузка и очистка SCADA-данных турбин, почасовая агрегация.

В исходных файлах 10-минутные записи: время (местное), средняя скорость ветра
на гондоле, нормализованная активная мощность (доля от номинала) и температура.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import settings as S

COLS = ["id", "time", "ws", "p", "temp"]

# Минимальное число 10-минутных записей в часе, чтобы час считался измеренным.
MIN_RECORDS_PER_HOUR = 4


def load_turbine_10min(path: Path | str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = COLS
    df["time"] = pd.to_datetime(df["time"], format="%Y-%m-%d %H:%M:%S")
    df = df.drop(columns="id").drop_duplicates("time").set_index("time").sort_index()
    # физические границы
    df.loc[(df["ws"] < 0) | (df["ws"] > 50), "ws"] = np.nan
    df.loc[(df["p"] < 0) | (df["p"] > 1.05), "p"] = np.nan
    df.loc[(df["temp"] < -50) | (df["temp"] > 55), "temp"] = np.nan
    return df


def flag_anomalies(df: pd.DataFrame, curve: "PowerCurve | None" = None) -> pd.Series:
    """Флаг записей, которые не отражают нормальную работу турбины.

    * застывший датчик ветра (одинаковое значение 6+ раз подряд при ветре > 1 м/с);
    * простой: мощность ~0 при ветре заметно выше скорости включения;
    * сильное недобирание мощности относительно кривой (ограничение, обмерзание).
    """
    bad = pd.Series(False, index=df.index)
    same = df["ws"].diff().eq(0)
    run_len = same.groupby((~same).cumsum()).transform("sum")
    bad |= same & (run_len >= 6) & (df["ws"] > 1)
    bad |= (df["p"] <= 0.005) & (df["ws"] > 5.0)
    if curve is not None:
        expected = curve.predict(df["ws"].to_numpy())
        bad |= (df["ws"] > 7.0) & (df["p"] < 0.35 * expected)
    return bad


def to_hourly(df: pd.DataFrame, bad: pd.Series | None = None) -> pd.DataFrame:
    """Почасовые средние. Метка часа - его начало (00:00 = интервал 00:00-00:59)."""
    x = df.copy()
    if bad is not None:
        x.loc[bad, ["ws", "p"]] = np.nan
    g = x.resample("1h")
    out = g.mean()
    out["n"] = g["p"].count()
    out.loc[out["n"] < MIN_RECORDS_PER_HOUR, ["ws", "p"]] = np.nan
    return out


class PowerCurve:
    """Эмпирическая кривая мощности: медиана мощности в бинах скорости 0.5 м/с,
    монотонно сглаженная. Используется как физический прайор и базовая модель."""

    def __init__(self, bin_width: float = 0.5, max_ws: float = 30.0):
        self.bin_width = bin_width
        self.max_ws = max_ws
        self.centers: np.ndarray | None = None
        self.values: np.ndarray | None = None

    def fit(self, ws: np.ndarray, p: np.ndarray) -> "PowerCurve":
        ws = np.asarray(ws, float)
        p = np.asarray(p, float)
        m = np.isfinite(ws) & np.isfinite(p)
        ws, p = ws[m], p[m]
        edges = np.arange(0, self.max_ws + self.bin_width, self.bin_width)
        idx = np.digitize(ws, edges) - 1
        centers, values = [], []
        for i in range(len(edges) - 1):
            sel = idx == i
            if sel.sum() >= 30:
                centers.append(edges[i] + self.bin_width / 2)
                values.append(np.median(p[sel]))
        c, v = np.array(centers), np.array(values)
        if not len(v):
            raise ValueError("not enough observations: need at least 30 valid samples in a wind bin")
        v = np.maximum.accumulate(v)  # кривая мощности не убывает до отключения
        # выше последнего надёжного бина держим номинал
        self.centers = np.concatenate([[0.0], c, [self.max_ws]])
        self.values = np.concatenate([[0.0], v, [v[-1]]])
        return self

    def predict(self, ws: np.ndarray) -> np.ndarray:
        assert self.centers is not None, "curve is not fitted"
        return np.interp(np.asarray(ws, float), self.centers, self.values)

    def expected(self, ws: np.ndarray, sigma: np.ndarray | float) -> np.ndarray:
        """Ожидаемая мощность при неопределённости ветра N(ws, sigma):
        E[P(ws + e)]. Сглаживает кривую там, где прогноз ветра неточен."""
        ws = np.asarray(ws, float)[:, None]
        sigma = np.broadcast_to(np.asarray(sigma, float), ws.shape[:1])[:, None]
        nodes = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
        w = np.exp(-0.5 * nodes ** 2)
        w = w / w.sum()
        pts = np.clip(ws + sigma * nodes[None, :], 0, None)
        return (self.predict(pts.ravel()).reshape(pts.shape) * w).sum(axis=1)

    def to_dict(self) -> dict:
        return {"centers": self.centers.tolist(), "values": self.values.tolist()}

    @classmethod
    def from_dict(cls, d: dict) -> "PowerCurve":
        pc = cls()
        pc.centers = np.array(d["centers"])
        pc.values = np.array(d["values"])
        return pc


def load_all_hourly(turbines=None, curve_until_local: pd.Timestamp | None = None
                    ) -> tuple[pd.DataFrame, dict[int, PowerCurve]]:
    """Почасовые данные обеих турбин в длинном формате + кривые мощности.

    Кривые мощности строятся только по данным до curve_until_local (если задано),
    чтобы при валидации в прошлом не использовать будущие факты.
    Возвращает DataFrame с колонками: time_local, time_utc, turbine, ws, p, temp, n.
    """
    turbines = turbines or S.TURBINES
    frames, curves = [], {}
    for t in turbines:
        raw = load_turbine_10min(t["file"])
        fit_mask = raw.index < curve_until_local if curve_until_local is not None else np.ones(len(raw), bool)
        pre_bad = flag_anomalies(raw)
        sel = fit_mask & ~pre_bad.to_numpy()
        curve = PowerCurve().fit(raw.loc[sel, "ws"].to_numpy(), raw.loc[sel, "p"].to_numpy())
        bad = flag_anomalies(raw, curve)
        sel = fit_mask & ~bad.to_numpy()
        curve = PowerCurve().fit(raw.loc[sel, "ws"].to_numpy(), raw.loc[sel, "p"].to_numpy())
        h = to_hourly(raw, bad)
        h["turbine"] = t["id"]
        h["bad_share"] = bad.resample("1h").mean().reindex(h.index).fillna(0.0)
        frames.append(h)
        curves[t["id"]] = curve
    df = pd.concat(frames).rename_axis("time_local").reset_index()
    df["time_utc"] = df["time_local"] - pd.Timedelta(hours=S.SCADA_UTC_OFFSET_H)
    return df, curves


def farm_hourly(long: pd.DataFrame) -> pd.DataFrame:
    """Выработка ВЭС = среднее нормализованной мощности доступных турбин."""
    wide = long.pivot_table(index="time_local", columns="turbine", values="p")
    wide.columns = [f"p{c}" for c in wide.columns]
    wide["farm"] = wide.mean(axis=1, skipna=True)
    return wide
