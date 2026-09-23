# Low Prior Wind

Почасовой прогноз нормализованной мощности двух турбин на 24–48 часов: **React → FastAPI → агент → погода/модель → SQLite**. Исходное ТЗ сохранено без изменений в [docs/implementation-spec.md](docs/implementation-spec.md).

Реализованы API, dashboard, импорт SCADA, три обучаемых алгоритма, погодные снимки с происхождением, дневной replay, CSV, журнал решений, обновление по fingerprint и тесты. Сквозной сценарий работает на явно обозначенной синтетической погоде. **Проверенный конкурсный прогноз за февраль не заявляется:** фактов за февраль нет, историческая публикация имеющегося архива погоды не подтверждена.

## Запуск

Нужны Node.js 22.12+ (либо 24+) и [uv](https://docs.astral.sh/uv/getting-started/installation/). Из корня репозитория:

```powershell
uv sync --locked
npm ci
npm run dev
```

| Сервис | Адрес |
|---|---|
| Dashboard | http://127.0.0.1:5173 |
| API | http://127.0.0.1:8000 |
| Swagger / OpenAPI | http://127.0.0.1:8000/docs / http://127.0.0.1:8000/openapi.json |
| Health | http://127.0.0.1:8000/health |

Оставьте Synthetic demo / Demo power curve, нажмите «Запустить прогноз». Две турбины × 48 часов дают 96 значений, журнал и CSV. «Проверить новые входы» возвращает прежний ID, если входы не изменились. Run daily replay создаёт дневные выпуски; без фактов MAE/RMSE отсутствуют.

Раздельно: `npm run dev:api` / `npm run dev:web`. Остановка — Ctrl+C. Backend без auto-reload: после изменений Python требуется перезапуск. Только один API worker с одной SQLite.

На текущей Windows-машине зависимости уже установлены: достаточно `npm run dev`. Если uv не найден в PATH: `.\.venv\Scripts\uv.exe sync --locked --cache-dir .uv-cache`. Вместо `uv run python` можно использовать `.\.venv\Scripts\python.exe`.

Необязательная настройка: скопировать `.env.example` в `.env`. Параметры: `WINDFARM_DB`, `WINDFARM_TURBINES`, `WINDFARM_WEATHER_CACHE`. Локальную конфигурацию турбин хранить в `config/turbines.local.json`.

## Площадка и временной контракт

- Координаты подтверждены: turbine-1 — **43.645139, 78.535611**, turbine-2 — **43.643198, 78.538828**.
- SCADA — постоянный **UTC+6**, выведен из корреляции ветра и принят командой. API и UI используют UTC.
- Мощность — **доля номинала [0,1]**. Номинал и высота ступицы не заданы условием, в конфигурации null. Пересчёта в MW нет.
- Выпуск **07:00 UTC** — настраиваемое решение команды, не официальное время кейса.
- Прогноз — **T+1…T+24/48**, timestamp означает конец часа. Это rolling horizon, не календарные сутки D+1/D+2.

## Реальные данные и модели

```powershell
# 60 минут — явное допущение о задержке поступления, не факт из условия.
uv run python scripts/convert_scada.py --latency-minutes 60
uv run python scripts/import_csv.py data/canonical/observations.csv --name case-scada --provenance "Case SCADA; UTC+6; interval-end UTC; assumed 60-minute latency; stoppages preserved"
uv run python scripts/data_report.py
uv run python scripts/validate_models.py
```

Конвертер требует минимум четыре валидные записи в часе, сохраняет реальные простои в target, переводит начало часа UTC+6 в конец часа UTC. Исходники не меняет, значения не обрезает. Получается **48 647 часов**; преобразования и допущения записываются в metadata JSON.

В UI можно импортировать canonical CSV/JSON и обучить:

| Алгоритм | Назначение |
|---|---|
| binned-curve | Медианная монотонная кривая; различие SCADA-ветра и NWP отмечено предупреждением |
| persistence | Последняя мощность, доступная к issue time |
| weather-ridge | Ridge-кандидат на issue/valid/turbine-парах из проверенной погоды, lead и прошлой мощности |

Дата обучения проверяется по времени факта и доступности. Использовать модель до cutoff нельзя. Артефакт хранит версию, параметры, fingerprint и dataset ID. Калиброванные интервалы пока не реализованы.

`artifacts/validation.json` содержит persistence-бейзлайн на октябре 2025–январе 2026, отдельно по турбинам и горизонтам. Для погодных моделей передайте `--snapshots verified.json`; без подтверждённых снимков они отмечаются недоступными. Февраль для выбора модели не используется.

Искусственный пример — `examples/observations.demo.csv`. При импорте включите «Искусственные данные» или используйте `scripts/import_csv.py ... --demo`. Модель останется DEMO даже с настоящей погодой.

## Погода и защита от будущих данных

Single Runs adapter сохраняет исходный ответ, проверяет единицы, UTC, null и полноту. Кандидат — unverified, без выдуманного available_at. Повторы ограничены тремя попытками и журналируются. Проверенную ревизию импортируют с новым ID; записи неизменяемы.

Archive mode требует kind=forecast, verification=verified, непустое доказательство, available_at <= issued_at и все нужные часы. При неполном новом запуске выбирается более ранний допустимый. Синтетического fallback нет.

```powershell
uv run python scripts/import_weather_archive.py
uv run python -m wind_agent.worker --run-id run-REPLACE --interval 60
```

Импорт исходных CSV создаёт **неподтверждённые кандидаты**. Watcher проверяет новые входы фиксированного выпуска; ежедневное планирование и автоматическая верификация публикации не реализованы.

В [описании Single Runs](https://open-meteo.com/en/docs/single-runs-api), проверенном 23.09.2026, ранний ECMWF обозначен IFS Cycle 49R1 hindcasts; run — инициализация, не публикация. Покрытие CSV и допущение «плюс 6 часов» не доказывают историческую доступность. [Условия Open-Meteo](https://open-meteo.com/en/terms).

## API и архитектура

Все бизнес-маршруты начинаются с `/api/v1`; полные схемы в Swagger.

| Метод | Путь |
|---|---|
| GET | /turbines |
| GET / POST | /datasets |
| GET | /datasets/{id}/observations?start=…&end=… |
| GET / POST | /models / /models/train |
| GET / POST | /weather/snapshots |
| POST | /weather/fetch |
| GET / POST | /forecasts |
| GET | /forecasts/{id}, /forecasts/{id}/events, /forecasts/{id}/export |
| POST | /forecasts/{id}/refresh |
| GET / POST | /backtests |
| GET | /backtests/{id}, /backtests/{id}/export |

Jobs: queued → running → succeeded/failed. HTTP 202 означает очередь. Ошибки: {code,message}; 404 — ресурс, 409 — конфликт/нет архива/экспорт не готов, 422 — входы, 503 — погодный transport. После рестарта незавершённые jobs помечаются failed.

`agent/wind_agent` — политика и погода; `backend/wind_backend` — HTTP, SQLite, ML, оценка; `contracts/wind_contracts` — общие типы; `frontend` — React; `windagent` — исходный исследовательский слой; `scripts` — конвертеры и проверки.

## Проверки и демонстрация

```powershell
npm run contracts
npm run check
# При запущенном npm run dev:
uv run python scripts/smoke_demo.py
```

Check запускает Python lint, pytest, TypeScript и production build. CI также проверяет drift OpenAPI/TS и smoke через Vite proxy. Сгенерированные контракты коммитятся вместе, вручную не редактируются.

Smoke проверяет импорт, обучение, 96 точек, refresh reuse, 29 дневных выпусков и экспорт. `artifacts/february-demo.csv` и `february-demo-report.json` — **DEMO**, без заявлений о точности. [Сценарий показа](docs/demo.md).

## Оставшиеся ограничения

- Нужны независимые доказательства оригинальной погоды и публикации для честного февральского replay.
- Weather-ridge требует оценки на таком архиве; улучшение над baseline не заявляется.
- Семантика исходных 10-минутных меток и реальная latency требуют уточнения, если организатор их предоставит.
- Номиналы неизвестны, станционный MW-агрегат отключён. Калиброванных квантилей нет.
- Визуальная desktop/mobile проверка остаётся ручной: управляемый браузер в среде недоступен. Сборка и HTTP-поток проверены.
- Приложение локальное: один worker, SQLite JSON, без auth, внешней очереди и production deployment.

Подробнее: [Agent](docs/agent.md), [Backend/ML](docs/backend.md), [Frontend](docs/frontend.md), [Данные/replay](docs/data-and-replay.md), [Исходное ТЗ](docs/implementation-spec.md).
