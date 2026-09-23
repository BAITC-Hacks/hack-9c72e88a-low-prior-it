"""Параметры площадки и эксперимента. Только стандартная библиотека."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Минимальная загрузка .env (KEY=VALUE) без внешних зависимостей."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
WEATHER_DIR = DATA_DIR / "weather"
CACHE_DIR = WEATHER_DIR / "cache"
OUTPUT_DIR = ROOT / "outputs"
MODEL_DIR = ROOT / "models"
DB_PATH = OUTPUT_DIR / "agent_memory.sqlite"

# Координаты турбин из условия кейса (Шелекский коридор, Алматинская область).
# Турбина 1: 43°38'42.5"N 78°32'08.2"E, турбина 2: 43.643198, 78.538828.
TURBINES = [
    {
        "id": 1,
        "name": "turbine_1",
        "lat": 43.645139,
        "lon": 78.535611,
        "file": RAW_DIR / "turbine_1.csv",
    },
    {
        "id": 2,
        "name": "turbine_2",
        "lat": 43.643198,
        "lon": 78.538828,
        "file": RAW_DIR / "turbine_2.csv",
    },
]

# Шкала времени SCADA - UTC+6 (прежнее время Алматы). Определено по максимуму
# корреляции ветра SCADA с прогнозом ECMWF: пик на сдвиге 6 ч, одинаково в 2024
# и 2025 годах, т.е. часы SCADA не переводили при переходе Казахстана на UTC+5
# 01.03.2024. Все входы и выходы проекта - в этой шкале ("местное" время ниже).
SCADA_UTC_OFFSET_H = 6

# Прогноз выпускается в 12:00 по времени Астаны (UTC+5) = 13:00 по шкале SCADA
# = 07:00 UTC дня D, на сутки D+1 и D+2 (почасово, 48 значений). Используется
# последний запуск модели погоды, опубликованный к этому моменту.
ISSUE_HOUR_LOCAL = 13
NWP_MODEL = "ecmwf_ifs"  # ECMWF IFS HRES 9 km
NWP_PUBLISH_DELAY_H = 6  # запуск становится доступен через ~6 ч
NWP_CYCLE_H = 6  # запуски 00/06/12/18 UTC
SECOND_MODELS = ["gfs_seamless", "icon_seamless"]

ARCHIVE_START = date(2024, 3, 14)  # начало архива Single Runs для ECMWF IFS
TRAIN_END = date(2026, 1, 31)  # последние известные факты
TEST_START = date(2026, 2, 1)
TEST_END = date(2026, 2, 28)

# Ключ NVIDIA Build (OpenAI-совместимый API). Без ключа агент работает
# на детерминированном планировщике.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "meta/llama-3.3-70b-instruct")
LLM_API_KEY = os.getenv("NVIDIA_API_KEY") or os.getenv("LLM_API_KEY") or ""


def turbine_coords() -> tuple[list[float], list[float]]:
    return [t["lat"] for t in TURBINES], [t["lon"] for t in TURBINES]
