# PR title

Add leakage-safe CatBoost training and fixed UTC+06 SCADA preparation

## Change

Area: Agent / Backend-ML. Adds organizer CSV preparation, hourly SCADA statistics,
origin-safe features, persistence and per-turbine CatBoost behind the existing
Predictor interface. Users can train, reload and compare the models locally without
LLM credentials. Daily chronological validation reports MAE/RMSE separately for
each turbine and the 1–24 / 25–48-hour horizons.

Source timestamps are confirmed as **fixed UTC+06:00, interval start**. For example,
`2026-01-01 06:00` represents the first ten minutes of the UTC hour; its canonical
interval-end time is `2026-01-01T00:10:00Z`. The corrected preparation uses this
rule across the entire 2023–2026 history, rather than applying Almaty civil-time
offset changes. Original files and prior forecast/model revisions are retained.

## Contracts and integration

- `POST /api/v1/models/train` accepts an additive algorithm selector, CatBoost
  feature mode, daily origin window and bounded training parameters. Existing
  requests still train the binned baseline by default.
- OpenAPI and generated TypeScript are updated. Predictor/WeatherProvider
  signatures and existing forecast/replay routes are preserved.
- CatBoost supports SCADA-only features or verified forecast-weather plus SCADA.
  Archive mode requires publication at/before origin and full hourly coverage.
  Future observed weather is never used as a substitute.
- Model files use native `.cbm` serialization with checksums and a manifest.
  `WINDFARM_MODELS` configures the artifact directory; default `artifacts/models`.
- Numerical inputs and labels obey both event-time and availability cutoffs.
  Model prediction checks its own training cutoff, and scoring rejects duplicate actuals.
- Dependencies are declared/locked. Dataset, database and model binaries are
  local ignored files; no raw organizer data or credentials are included.
- Current `origin/main` (`20bcb69`) was merged into `ml-aiagent` without conflicts.
  Frontend changes from main are preserved; ML changes touch only generated frontend types.

## Validation

- Python 3.13: **78 tests passed**. One existing Starlette/httpx deprecation warning.
- Ruff: passed; `git diff --check`: passed.
- `uv lock --check --offline`: passed.
- OpenAPI equals the running application's schema; TypeScript regenerated.
- `npm run build`: TypeScript checks and Vite production build passed with main's UI.
- Corrected real-data experiment: 48,452 complete hourly observations, 91,720
  training issue/target samples, 2,688 scored January validation pairs, zero
  missing validation actuals. Fixed parameters; February was not used for tuning.
- Mean MAE: CatBoost **0.29834**, persistence **0.34360** (13.2% lower).
  Per-turbine/horizon MAE and RMSE: [training results](initial-training-results.md).
- Reproduction and exact preparation assumptions: [ML training](ml-training.md).

## Remaining limitations

- Power normalization definition and SCADA reporting delay remain unknown. The
  experiment retains source values in [0,1] and assumes a 10-minute delay after
  interval end. Models retain `is_demo=true` as a provisional-results label.
- No verified weather archive or February actuals was supplied. Current measured
  results are for the SCADA-only baseline on January, not official February scoring.
- CatBoost improves on persistence in this holdout but absolute errors remain high.
  Weather integration and an agreed validation protocol are still required.
- Training is synchronous in the local API; prefer the CLI for longer jobs.

## Local release handoff

The current registered model is `model-27c6f4072b7a441d80ede55745eb4f60`.
The earlier `model-02a5530154014db586f1320405a54ae2` used superseded time semantics
and is retained for audit only. Model IDs are local to this developer database;
teammates must prepare their authorized data and train to obtain their own IDs.

Base branch: `main`. Head branch: `ml-aiagent`. This file is a ready-to-copy PR body;
it does not mean a PR has been published or the feature branch merged into main.
