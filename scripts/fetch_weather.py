"""Скачивает архив прогнозов погоды для обучения и тестового февраля 2026.

Работает только на стандартной библиотеке Python 3.10+.

    python scripts/fetch_weather.py --smoke     # один запрос, проверка доступа
    python scripts/fetch_weather.py             # всё: тестовый месяц + история + вторая модель
    python scripts/fetch_weather.py --only-test # только запуски для 30.01-28.02.2026

Повторный запуск докачивает только то, чего нет в кэше data/weather/cache.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from windagent import openmeteo as om  # noqa: E402
from windagent import settings as S  # noqa: E402


def utc(y, m, d, h=0) -> datetime:
    return datetime(y, m, d, h, tzinfo=timezone.utc)


def build_single_run_jobs(only_test: bool) -> list[datetime]:
    jobs: list[datetime] = []
    # 1) тестовый период: все четыре запуска в сутки, чтобы агент мог пересчитывать
    d = date(2026, 1, 29)
    while d <= S.TEST_END:
        for h in (0, 6, 12, 18):
            jobs.append(utc(d.year, d.month, d.day, h))
        d += timedelta(days=1)
    if only_test:
        return jobs
    # 2) история для обучения: запуск 00 UTC каждых суток, от новых к старым
    d = date(2026, 1, 28)
    while d >= S.ARCHIVE_START:
        jobs.append(utc(d.year, d.month, d.day, 0))
        d -= timedelta(days=1)
    return jobs


def smoke() -> bool:
    lats, lons = S.turbine_coords()
    run = utc(2026, 1, 31, 0)
    print(f"[smoke] Single Runs API, model={S.NWP_MODEL}, run={run:%Y-%m-%dT%H:%M}Z")
    try:
        locs = om.fetch_single_run(run, lats, lons, S.CACHE_DIR, model=S.NWP_MODEL, use_cache=False)
    except Exception as e:  # noqa: BLE001
        print(f"[smoke] ОШИБКА: {e}")
        return False
    for i, loc in enumerate(locs):
        times, series = om.parse_hourly(loc)
        filled = {k: sum(v is not None for v in vals) for k, vals in series.items()}
        print(f"[smoke] loc{i+1}: lat={loc.get('latitude')} lon={loc.get('longitude')} "
              f"elev={loc.get('elevation')} hours={len(times)} first={times[0] if times else None} "
              f"last={times[-1] if times else None}")
        print(f"[smoke]   non-null per variable: {filled}")
    return True


def run_single_runs(jobs: list[datetime], workers: int) -> list[datetime]:
    lats, lons = S.turbine_coords()
    todo = [r for r in jobs if not om.single_run_cache_path(S.CACHE_DIR, S.NWP_MODEL, r).exists()]
    print(f"[single-runs] всего запусков {len(jobs)}, в кэше {len(jobs) - len(todo)}, скачать {len(todo)}")
    failed: list[datetime] = []
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(om.fetch_single_run, r, lats, lons, S.CACHE_DIR, S.NWP_MODEL): r for r in todo}
        for fut in as_completed(futs):
            r = futs[fut]
            done += 1
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001
                failed.append(r)
                print(f"  ! {r:%Y-%m-%d %H}Z: {str(e)[:200]}")
            if done % 25 == 0 or done == len(todo):
                el = time.time() - t0
                eta = el / done * (len(todo) - done)
                print(f"  {done}/{len(todo)}  {el:5.0f} c прошло, ~{eta:5.0f} c осталось, ошибок {len(failed)}")
    return failed


def run_previous_runs() -> None:
    lats, lons = S.turbine_coords()
    chunks = []
    start = date(2024, 1, 1)
    while start <= S.TEST_END:
        end = min(date(start.year + (start.month + 2) // 12, (start.month + 2) % 12 + 1, 1) - timedelta(days=1), S.TEST_END)
        chunks.append((start, end))
        start = end + timedelta(days=1)
    for model in S.SECOND_MODELS:
        for a, b in chunks:
            path = om.previous_runs_cache_path(S.CACHE_DIR, model, a, b)
            if path.exists():
                continue
            try:
                om.fetch_previous_runs(a, b, lats, lons, S.CACHE_DIR, model=model)
                print(f"[previous-runs] {model} {a}..{b} ok")
            except Exception as e:  # noqa: BLE001
                print(f"[previous-runs] {model} {a}..{b} ОШИБКА: {str(e)[:200]}")


def compile_csv() -> None:
    """Собирает кэш JSON в плоские CSV для обучения."""
    out = S.WEATHER_DIR / f"{S.NWP_MODEL}_single_runs.csv"
    files = sorted((S.CACHE_DIR / "single_runs" / S.NWP_MODEL).glob("*.json"))
    n = 0
    with out.open("w", newline="", encoding="utf-8") as f:
        w = None
        for p in files:
            run = datetime.strptime(p.stem, "%Y%m%d%H").replace(tzinfo=timezone.utc)
            locs = om._as_list(json.loads(p.read_text(encoding="utf-8")))
            for li, loc in enumerate(locs):
                times, series = om.parse_hourly(loc)
                if w is None:
                    cols = ["run_utc", "loc", "valid_utc", "lead_h"] + list(series.keys())
                    w = csv.writer(f)
                    w.writerow(cols)
                    keys = list(series.keys())
                for i, t in enumerate(times):
                    lead = (t - run).total_seconds() / 3600
                    w.writerow([run.strftime("%Y-%m-%d %H:%M"), li + 1, t.strftime("%Y-%m-%d %H:%M"), int(lead)]
                               + [series.get(k, [None] * len(times))[i] for k in keys])
                    n += 1
    print(f"[compile] {out.relative_to(ROOT)}: {len(files)} запусков, {n} строк")

    for model in S.SECOND_MODELS:
        files = sorted((S.CACHE_DIR / "previous_runs" / model).glob("*.json"))
        if not files:
            continue
        out = S.WEATHER_DIR / f"{model}_previous_runs.csv"
        n = 0
        with out.open("w", newline="", encoding="utf-8") as f:
            w = None
            for p in files:
                locs = om._as_list(json.loads(p.read_text(encoding="utf-8")))
                for li, loc in enumerate(locs):
                    times, series = om.parse_hourly(loc)
                    if w is None:
                        keys = list(series.keys())
                        w = csv.writer(f)
                        w.writerow(["loc", "valid_utc"] + keys)
                    for i, t in enumerate(times):
                        w.writerow([li + 1, t.strftime("%Y-%m-%d %H:%M")] + [series.get(k, [None] * len(times))[i] for k in keys])
                        n += 1
        print(f"[compile] {out.relative_to(ROOT)}: {n} строк")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="только проверка доступа")
    ap.add_argument("--only-test", action="store_true", help="только запуски тестового периода")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--skip-previous", action="store_true")
    args = ap.parse_args()

    if not smoke():
        print("Проверьте интернет и доступ к single-runs-api.open-meteo.com")
        sys.exit(1)
    if args.smoke:
        return
    jobs = build_single_run_jobs(args.only_test)
    failed = run_single_runs(jobs, args.workers)
    if failed:
        print(f"[single-runs] повтор для {len(failed)} запусков")
        failed = run_single_runs(failed, max(1, args.workers // 2))
    if not args.skip_previous:
        run_previous_runs()
    compile_csv()
    print("Готово." if not failed else f"Готово, но {len(failed)} запусков не скачались: запустите скрипт ещё раз.")


if __name__ == "__main__":
    main()
