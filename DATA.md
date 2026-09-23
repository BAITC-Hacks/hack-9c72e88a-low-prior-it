# Данные и погода

Актуальные правила: [docs/data-and-replay.md](docs/data-and-replay.md). Прежние исследовательские заметки сохранены в [docs/legacy-data-notes.md](docs/legacy-data-notes.md); их заявления о безусловной исторической доступности погоды не являются контрактом новой системы.

| Файл | Строк | Период |
|---|---:|---|
| data/raw/turbine_1.csv | 142 360 | 11.03.2023–31.01.2026, 10 минут с пропусками |
| data/raw/turbine_2.csv | 149 499 | Тот же период |
| data/weather/ecmwf_ifs_single_runs.csv.gz | 116 064 | 806 запусков, 14.03.2024–28.02.2026 |
| data/weather/gfs_seamless_previous_runs.csv.gz | 37 920 | 01.01.2024–28.02.2026 |
| data/weather/icon_seamless_previous_runs.csv.gz | 37 920 | Тот же период |

SCADA содержит ветер, нормализованную мощность и температуру. Null в исходных CSV нет, отсутствуют целые записи. После canonical-агрегации с минимумом четырёх записей: 23 728 часов первой турбины и 24 919 второй. Февральских фактов нет.

UTC+6 выведен по корреляции ветра и принят владельцем проекта. API использует явный UTC и конец часового интервала. Координаты подтверждены; номинал и высота ступицы не заданы условием.

Старый `windagent/scada.py` строит кривую нормальной работы с фильтрацией простоев. Новый `scripts/convert_scada.py` сохраняет допустимые простои/ограничения в фактическом target и не обучает очистку на будущих данных.

В ECMWF по 144 пропуска у ветра 100 м, направления, температуры, влажности и давления; у порывов 1 612, осадков 1 754. Во вторых моделях отсутствует примерно 2.3–6.1% значений в зависимости от поля. Старое утверждение «меньше 0.2%» не относится ко всем архивам.

```powershell
uv run python scripts/data_report.py
uv run python scripts/convert_scada.py --latency-minutes 60
uv run python scripts/validate_models.py
uv run pytest -q
```

`artifacts/data-report.json` показывает покрытия, пропуски, разрывы, кривые и корреляции временных сдвигов. `validation.json` — persistence-бейзлайн до февраля с MAE/RMSE по турбинам и горизонтам. 60 минут latency — явное допущение в sidecar metadata.

Погодные CSV содержат run/valid time, но не доказательство публикации. [Single Runs API](https://open-meteo.com/en/docs/single-runs-api) обозначает ранний ECMWF как Cycle 49R1 hindcasts. `scripts/import_weather_archive.py` импортирует их как unverified. Новый агент требует verified original forecasts с evidence и available_at до issue. Шестичасовая задержка в старом settings.py — исследовательское допущение, а не доказательство.

GFS/ICON доступны в исследовательском слое и автоматически в новый predictor не включаются. Исходники сохранены без изменений; новые canonical-файлы, SQLite, raw cache и артефакты игнорируются Git.
