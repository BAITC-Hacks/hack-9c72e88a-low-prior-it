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

The importer rejects duplicate turbine/hour keys, naive timestamps, nonfinite values, and out-of-contract ranges. It does not infer timezones, normalize targets, resample subhourly measurements, deduplicate source data, or distinguish missing power from shutdowns. Those are explicit backend preprocessing tasks.

Historical timezone rules matter for a series spanning 2023–2026. Confirm whether source timestamps are local civil time, UTC, or fixed-offset plant time, including any changes. Preserve original values in raw data and record the mapping to UTC.

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
