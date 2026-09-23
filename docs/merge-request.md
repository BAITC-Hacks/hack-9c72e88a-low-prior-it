# PR title

Improve CatBoost through chronological selection and confirmed SCADA timing

## Change

The initial SCADA CatBoost had January MAE 0.29834. Selection among four predefined
configurations on November/December folds chooses a compact MAE model: January
MAE becomes **0.28006 (6.13% lower)** and RMSE **0.33508 (1.64% lower)** on the same
2,688 forecast pairs. Every turbine/horizon group improves. January is excluded
from parameter selection; its prior baseline score had already been inspected.

The winner is refitted separately with a January 31 cutoff for later forecasts.
January comparison scores belong to the January 1 model, not the refitted weights.
Both are registered locally with immutable IDs.

## Implementation

- Preserve confirmed UTC+06:00 / interval-start preparation and explicit assumptions
  for unknown reporting delay and normalization.
- Add optional versioned weekly SCADA features, MAE loss, bounded L2 and 6/12/24-hour
  origin steps. Existing defaults/artifacts stay compatible. Weekly lags did not win.
- Add reproducible chronological selection, weighted scoring, coverage checks,
  frozen plan/winner records, interrupted-fold recovery and source-checked refitting.
- Regenerate API schemas/types and align the existing dashboard training request.
  Preserve main's weather ridge, provenance fields and data/weather integration.
- Merge `origin/main` at `1ac833c` into `ml-aiagent`, resolving integration conflicts.
  Keep the architecture and Predictor/WeatherProvider interfaces.
- Retain original artifacts and data. New weights, predictions and database remain
  ignored; the PR includes a metric/provenance summary, not additional raw data.

## Validation

- **102 tests passed**; one existing Starlette/httpx deprecation warning.
- Ruff and offline `uv lock --check` passed; `git diff --check` passed.
- OpenAPI matches the application; generated TypeScript is current.
- `npm ci` and `npm run build` passed, including main's CSV importer.
- Previous and selected model reloads reproduce saved January predictions exactly
  for 96 points each.
- Refit completes the existing agent flow: 96 predictions, both turbines, 48 hours,
  explicit provisional/SCADA-only labels.
- Eight development fits, one January fit, one later refit, each with two estimators.
  Per candidate: 2,660 scored development pairs, 28 missing; January: 2,688, no missing.

Evidence: [results](tuned-training-results.md), [metric summary](model-selection-results.json),
[commands and assumptions](ml-training.md).

## Limitations

The winner improves development MAE but slightly worsens development RMSE; January
improves on both. Errors remain large. Limited correlated windows do not establish
general superiority. Latency and physical normalization remain unconfirmed, so
`is_demo=true` remains. Main's weather CSVs await publication verification. No
verified February score exists; the full weather-based task.pdf workflow remains open.

## Local handoff

Evaluation: `model-1ce9040924c14cd583a3924c7860c2ee`, cutoff January 1.
Refit: `model-278bd6130ed3466ca981f75368f0df8e`, cutoff January 31, 00:00 UTC.
IDs are local: teammates prepare authorized data and run the documented commands.

Base: `main`. Head: `ml-aiagent`. This is a prepared PR body; no PR publication,
remote push or merge into main is implied.
