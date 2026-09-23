# Data, provenance, and replay agreement

## Dataset schema

| Field | Meaning |
| --- | --- |
| `turbine_id` | Configured asset ID |
| `valid_time` | End of the hourly measurement interval; timezone-aware |
| `available_at` | Earliest instant the measurement could have been used |
| `wind_speed_ms` | Mean observed wind, m/s; confirm sensor height |
| `temperature_c` | Ambient temperature, °C |
| `power_normalized` | Mean active power as capacity fraction, once source normalization is confirmed |

The HTTP importer rejects duplicate turbine/hour keys, naive timestamps, nonfinite values, and out-of-contract ranges. It does not infer timezones, normalize targets, resample subhourly measurements, deduplicate source data, or distinguish missing power from shutdowns. The offline SCADA foundation below prepares subhourly data before that import boundary.

Historical timezone rules matter for a series spanning 2023–2026. Confirm whether source timestamps are local civil time, UTC, or fixed-offset plant time, including any changes. Preserve original values in raw data and record the mapping to UTC.

For the supplied organizer files, the user confirmed fixed **UTC+06:00** and
10-minute **interval-start** timestamps. The source adapter converts to UTC and
adds 10 minutes before hourly interval-end aggregation. Use preparation revision
`utc6-start-provisional-v2`; the earlier `Asia/Almaty` interpretation is superseded.
The integrated data branch records owner confirmation of normalized power.
Reporting latency remains unconfirmed. Existing preparation/model artifacts retain
their recorded assumptions and provisional labels; this documentation update does
not retroactively change their provenance.

## SCADA foundation

`contracts/wind_contracts/scada.py` adds internal `ScadaReading` and `HourlyScada`
contracts without changing HTTP schemas. Deterministic preparation tools live in
`agent/wind_agent/scada.py`, temporal guards in `agent/wind_agent/temporal.py`.
Numerical prediction models remain behind `Predictor` in `backend/wind_backend/ml.py`.
The agent tools import shared contracts, never backend implementations.

This first foundation follows `docs/task.pdf`: hourly 24–48-hour forecasts and a
February 1–28, 2026 historical replay must use original weather forecasts available
at each issue time. It does not implement a new model, weather downloader, replay,
or LLM. The PDF also scores reproducibility; these helpers and their tests run offline.

```python
from datetime import datetime, timezone
from wind_agent.scada import aggregate_hourly, parse_scada_csv, profile_scada

# Canonical columns are the same six names as the observation CSV contract;
# valid_time may now be subhourly. All timestamps require explicit UTC offsets.
rows = parse_scada_csv("data/scada.canonical.csv")
profile = profile_scada(rows, interval_minutes=10)
origin = datetime(2026, 1, 31, tzinfo=timezone.utc)
hours = aggregate_hourly(rows, interval_minutes=10, forecast_origin=origin)
observations = [hour.to_observation() for hour in hours if hour.complete]
# These Observation objects are compatible with DatasetUpload and existing ML.
```

- `inspect_scada_csv` returns valid readings, source row count, and invalid row
  diagnostics with line numbers. This is a profiling result, not an approved clean
  dataset. `parse_scada_csv` rejects the entire input if any row is invalid or the
  file is empty. No silent clipping, filling, averaging duplicates, or normalization.
- Native headers require `columns={canonical_name: source_header, ...}` covering
  all six fields. Semicolon CSVs can pass `delimiter=";"`. UTF-8 BOM is supported.
  Missing `available_at` is an error: derive it upstream only from a documented,
  confirmed latency policy. Naive local timestamps must be converted upstream
  with confirmed historical timezone rules; no timezone is guessed here.
- Aggregation assumes equally spaced **interval-end averages**, aligned to a UTC
  sampling grid (10 minutes by default). `(T-1h, T]` belongs to hour `T`, including
  the reading exactly at `T`. Confirm this source convention before real ingestion.
  Irregular sampling is rejected rather than treated as equal-duration intervals.
- Preserved statistics: wind and power mean/std/min/max, temperature mean/std.
  Standard deviations use the population convention (`ddof=0`), so one reading
  has zero stddev. `power_mean` is the initial hourly target.
- `sample_count`, `expected_count`, and `complete` expose coverage. Missing hours
  remain absent; partially observed hours retain their statistics but cannot be
  converted by `to_observation()`. Missing readings are never zero production.
  Profiling counts missing slots between each turbine's first and last reading,
  zero-power readings, delayed arrivals, ranges, and hourly sample-count frequencies.
- With `forecast_origin`, raw readings are filtered by **both** `valid_time` and
  `available_at` before aggregation, and unfinished hourly intervals are omitted.
  Aggregate availability is the maximum of the hour end and contributor availability.
  Offline aggregation without an origin is useful for targets; before using such
  aggregates as features, filter them with `observations_as_of`. An offline hour
  containing delayed data cannot be treated as known earlier.
- `forecast_lead` enforces aligned future targets at leads 1–48.
  `validate_weather_timing` enforces initialization <= publication <= origin;
  it does not authenticate provenance. The existing `ForecastAgent` still enforces
  snapshot verification, turbine identity, and complete weather coverage.
  `validate_chronological_split` checks training target/availability cutoffs and
  strictly later validation targets. Feature construction must separately enforce
  its per-origin input lineage; no random split or target-relative SCADA lag is safe.

Run `uv run pytest tests/test_scada.py` and `uv run pytest` for focused and full
regression checks. Test readings and weather fixtures for the API are artificial.
The integrated data branch also includes raw SCADA and candidate weather CSVs;
these are separate from verified API snapshots. The owner confirms normalized power;
source timestamps are confirmed as fixed UTC+06:00 and interval start. Reporting
latency remains an assumption; rated capacity and hub height were not supplied.
Current models retain their recorded provenance and provisional label.

The integrated ML module includes origin-safe persistence, weather/SCADA features,
CatBoost, and a weather ridge candidate. Keep historical weather inputs distinct
from future observed weather, and retain forecast revision and model metadata contracts.

The preparation CLI supports both `dataset/turbine1.csv` (its original default)
and the merged filenames through `--input-dir data/raw --filename-pattern
'turbine_{number}.csv'`. Provide the timezone, timestamp position, and reporting
latency explicitly; use `--provisional` while these assumptions await confirmation.
For accepted fixed UTC+6 use `--timezone Etc/GMT-6`, rather than a civil timezone
whose offset changed. The legacy `convert_scada.py` permits four samples/hour;
the primary `prepare_dataset.py` retains only complete hours. Their output datasets
must keep distinct preparation metadata.

## Example rolling replay request

Send to `POST /api/v1/backtests`. These are **UTC demonstration boundaries**, pending agreement on the competition timezone and issue schedule:

```json
{
  "turbine_ids": ["turbine-1", "turbine-2"],
  "issued_at": "2026-01-31T00:00:00Z",
  "last_issued_at": "2026-02-28T00:00:00Z",
  "horizon_hours": 48,
  "weather_source": "demo",
  "model_id": "demo-power-curve",
  "evaluation_start": "2026-02-01T00:00:00Z",
  "evaluation_end": "2026-03-01T00:00:00Z",
  "actuals_dataset_id": null
}
```

Daily issue times are inclusive; the evaluation end is exclusive. The request is limited to 31 days between first and last issue times. Each child forecast retains its full horizon, while the backtest metrics/CSV include only target timestamps within the evaluation interval. Overlapping valid times are expected; issue time and lead distinguish the predictions.

Because targets are hour-end timestamps, if organizers define February as physical intervals from February 1 00:00 through March 1 00:00, the first hourly target ends February 1 01:00 and the last ends March 1 00:00. Shift the evaluation bounds accordingly (exclusive end at March 1 01:00), or adopt the organizer's stated timestamp convention consistently. Do not blindly reuse a calendar filter with the wrong interval semantics.

Actual observations are joined only for post-forecast scoring. Without matching actuals, the API reports unscored points and no invented metrics. Training does not happen inside replay: a fixed model ID is used, and its cutoff must precede the first issue.

## Provenance verification checklist

Record actual evidence, not just a check mark:

1. Original weather provider/model and exact initialization cycle.
2. Whether the source is an original operational forecast, a later hindcast, analysis, or reanalysis.
3. When that output was publicly available, including computation/distribution delay.
4. Requested and returned coordinates/grid cell, wind height, units, missingness, and temporal resolution.
5. Original payload/query checksum and a source URL/publication record.

Only original forecasts available by the issue time satisfy strict historical replay. A date parameter or an estimated publication lag does not prove this. The API records team-reviewed evidence but cannot authenticate external historical availability on its own.

## Before final scoring

- Agree whether February actuals may enter later forecasts after a reporting delay; the starter uses no such online refitting.
- Confirm target normalization and station aggregation weights.
- Fix hyperparameters and preprocessing from pre-February validation.
- Export every issue, turbine, valid time, lead, prediction, model ID, snapshot ID, initialization, and availability timestamp.
- Include error metrics by horizon and turbine, coverage counts, and baseline comparisons.
