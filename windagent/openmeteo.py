"""Клиент архивных прогнозов погоды Open-Meteo.

Только стандартная библиотека Python, чтобы скачивание работало на любой машине
без установки зависимостей.

Используются три API Open-Meteo (без ключа):

* Single Runs API - полный прогноз одного конкретного запуска модели
  (параметр run=YYYY-MM-DDTHH:MM, UTC). Для ECMWF IFS HRES 9 km архив запусков
  есть с 14.03.2024. Это ровно та информация, которая была у синоптика
  в момент выпуска прогноза, поэтому утечки будущего нет.
* Previous Runs API - значения, спрогнозированные за N суток до целевого часа
  (суффикс _previous_dayN). Используется для второй модели (GFS, ICON) как
  независимый источник и резерв.
* Forecast API - живой прогноз для работы агента в реальном времени.

Все ответы кэшируются на диск в data/weather/cache, поэтому повторный запуск
не ходит в сеть, а проверяющие могут воспроизвести результат офлайн.
"""
from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

SINGLE_RUNS_URL = "https://single-runs-api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Переменные основной модели (ECMWF IFS HRES 9 km). 100 м - ближе всего к высоте ступицы.
ECMWF_VARS: list[str] = [
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "wind_speed_100m",
    "wind_direction_100m",
    "temperature_2m",
    "relative_humidity_2m",
    "surface_pressure",
    "precipitation",
]

# Переменные второй модели через Previous Runs API.
PREV_BASE_VARS: list[str] = [
    "wind_speed_10m",
    "wind_speed_80m",
    "wind_direction_80m",
    "temperature_2m",
]
PREV_OFFSETS: list[int] = [1, 2, 3]

USER_AGENT = "hackalem-wind-agent/1.0 (+https://open-meteo.com)"


class OpenMeteoError(RuntimeError):
    pass


class _RateLimiter:
    """Не больше `rate` запросов в секунду на все потоки (лимит Open-Meteo 600/мин)."""

    def __init__(self, rate: float = 5.0):
        self.interval = 1.0 / rate
        self.lock = threading.Lock()
        self.next_t = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            if self.next_t > now:
                time.sleep(self.next_t - now)
                now = time.monotonic()
            self.next_t = now + self.interval


_limiter = _RateLimiter()


def get_json(url: str, params: dict, timeout: float = 120, retries: int = 6) -> object:
    """GET с повторами: 429 - пауза 60 с, 5xx и сетевые ошибки - экспоненциальная пауза."""
    query = urllib.parse.urlencode(params, safe=",:")
    full = f"{url}?{query}"
    last_err: Exception | None = None
    for attempt in range(retries):
        _limiter.wait()
        try:
            req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:400]
            last_err = OpenMeteoError(f"HTTP {e.code}: {body}")
            if e.code == 429:
                wait = 60.0
            elif e.code >= 500:
                wait = min(60.0, 2.0 ** attempt) + random.random()
            else:
                raise last_err from e  # 400 - ошибка параметров, повтор не поможет
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last_err = e
            wait = min(60.0, 2.0 ** attempt) + random.random()
        time.sleep(wait)
    raise OpenMeteoError(f"не удалось получить {full}: {last_err}")


def _as_list(payload: object) -> list[dict]:
    """Для нескольких координат API возвращает список, для одной - объект."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if payload.get("error"):
            raise OpenMeteoError(str(payload.get("reason")))
        return [payload]
    raise OpenMeteoError(f"неожиданный ответ: {type(payload)}")


def _atomic_write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Single Runs API
# ---------------------------------------------------------------------------

def single_run_cache_path(cache_dir: Path, model: str, run_utc: datetime) -> Path:
    return Path(cache_dir) / "single_runs" / model / f"{run_utc:%Y%m%d%H}.json"


def fetch_single_run(
    run_utc: datetime,
    lats: Sequence[float],
    lons: Sequence[float],
    cache_dir: Path,
    model: str = "ecmwf_ifs",
    variables: Sequence[str] = ECMWF_VARS,
    forecast_hours: int = 72,
    use_cache: bool = True,
    offline: bool = False,
) -> list[dict]:
    """Прогноз одного запуска модели для списка координат. Возвращает список локаций."""
    path = single_run_cache_path(cache_dir, model, run_utc)
    if use_cache and path.exists():
        return _as_list(json.loads(path.read_text(encoding="utf-8")))
    if offline:
        raise OpenMeteoError(f"нет в кэше и включён офлайн-режим: {path}")
    params = {
        "latitude": ",".join(f"{x:.6f}" for x in lats),
        "longitude": ",".join(f"{x:.6f}" for x in lons),
        "hourly": ",".join(variables),
        "models": model,
        "run": run_utc.strftime("%Y-%m-%dT%H:%M"),
        "forecast_hours": forecast_hours,
        "wind_speed_unit": "ms",
        "timezone": "GMT",
    }
    payload = get_json(SINGLE_RUNS_URL, params)
    locs = _as_list(payload)
    _atomic_write_json(path, payload)
    return locs


# ---------------------------------------------------------------------------
# Previous Runs API
# ---------------------------------------------------------------------------

def previous_runs_variables(base_vars: Iterable[str] = PREV_BASE_VARS,
                            offsets: Iterable[int] = PREV_OFFSETS) -> list[str]:
    out: list[str] = []
    for v in base_vars:
        for k in offsets:
            out.append(f"{v}_previous_day{k}")
    return out


def previous_runs_cache_path(cache_dir: Path, model: str, start: date, end: date) -> Path:
    return Path(cache_dir) / "previous_runs" / model / f"{start:%Y%m%d}_{end:%Y%m%d}.json"


def fetch_previous_runs(
    start: date,
    end: date,
    lats: Sequence[float],
    lons: Sequence[float],
    cache_dir: Path,
    model: str = "gfs_seamless",
    variables: Sequence[str] | None = None,
    use_cache: bool = True,
    offline: bool = False,
) -> list[dict]:
    variables = list(variables or previous_runs_variables())
    path = previous_runs_cache_path(cache_dir, model, start, end)
    if use_cache and path.exists():
        return _as_list(json.loads(path.read_text(encoding="utf-8")))
    if offline:
        raise OpenMeteoError(f"нет в кэше и включён офлайн-режим: {path}")
    params = {
        "latitude": ",".join(f"{x:.6f}" for x in lats),
        "longitude": ",".join(f"{x:.6f}" for x in lons),
        "hourly": ",".join(variables),
        "models": model,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "wind_speed_unit": "ms",
        "timezone": "GMT",
    }
    payload = get_json(PREVIOUS_RUNS_URL, params)
    locs = _as_list(payload)
    _atomic_write_json(path, payload)
    return locs


# ---------------------------------------------------------------------------
# Живой прогноз (режим реального времени)
# ---------------------------------------------------------------------------

def fetch_live_forecast(
    lats: Sequence[float],
    lons: Sequence[float],
    model: str = "ecmwf_ifs",
    variables: Sequence[str] = ECMWF_VARS,
    forecast_days: int = 3,
) -> list[dict]:
    params = {
        "latitude": ",".join(f"{x:.6f}" for x in lats),
        "longitude": ",".join(f"{x:.6f}" for x in lons),
        "hourly": ",".join(variables),
        "models": model,
        "forecast_days": forecast_days,
        "wind_speed_unit": "ms",
        "timezone": "GMT",
    }
    return _as_list(get_json(FORECAST_URL, params))


# ---------------------------------------------------------------------------
# Вспомогательное
# ---------------------------------------------------------------------------

def parse_hourly(loc: dict) -> tuple[list[datetime], dict[str, list]]:
    """Достаёт почасовые ряды из ответа одной локации. Время - UTC."""
    hourly = loc.get("hourly") or {}
    times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in hourly.get("time", [])]
    series = {k: v for k, v in hourly.items() if k != "time"}
    return times, series


def latest_available_run(issue_utc: datetime, delay_hours: float = 6.0,
                         cycle_hours: int = 6) -> datetime:
    """Последний запуск модели, который уже опубликован к моменту issue_utc.

    Глобальным моделям нужно ~4-6 часов после старта запуска, чтобы данные
    стали доступны. Берём консервативно delay_hours.
    """
    t = issue_utc - timedelta(hours=delay_hours)
    run_hour = (t.hour // cycle_hours) * cycle_hours
    return t.replace(hour=run_hour, minute=0, second=0, microsecond=0)
