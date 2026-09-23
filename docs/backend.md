# Backend and ML owner handoff

Branch: `backend`. Public routes are in `backend/wind_backend/routes.py`. The API is the integration boundary for the browser; `Predictor` is the integration boundary for the agent.

## Model contract

`predict(turbine, weather, issued_at)` must return exactly one `ForecastPoint` for each requested weather hour, sorted by valid time. IDs and lead times must match the request, and output must be finite normalized power in `[0,1]`. A different target scale requires an explicit schema update after understanding organizer normalization.

The demo model uses an illustrative cubic curve with assumed cut-in/rated/cut-out speeds of 3/12/25 m/s. These are not turbine specifications. The trainable baseline groups observed wind speed into 1 m/s bins for each turbine and averages normalized power. Prediction chooses the nearest populated bin; it does not extrapolate a physical cut-out curve. It is intentionally simple and may perform poorly outside observed wind regimes or when NWP wind is biased.

Model metadata contains a unique immutable ID, algorithm, training dataset, data cutoff, row count, turbine coverage, and demo flag. `WindService.predictor()` is the registry seam for new algorithms. Model artifacts are currently stored with SQLite records. Large serialized ML artifacts belong under `artifacts/` with metadata/checksums in the repository store.

## Training and evaluation agreement

1. Import original data with source-to-canonical mappings documented.
2. Make all filtering and transformations reproducible; separate instrumentation errors from real shutdown/curtailment.
3. Establish persistence, empirical-curve, and candidate ML baselines.
4. Use rolling chronological validation before February; fit scalers, imputers, and corrections within each training fold.
5. For a forecast issued at T, all SCADA features and model-fitting rows must have been available by T. A lag relative to target time may still be in the future relative to T.
6. Match training NWP inputs to operational lead times; measured-wind regression alone has a training/inference mismatch.
7. Freeze final model selection before scoring February. Refit during February only if organizers explicitly allow delayed actuals to enter the workflow.

`evaluation.py` computes MAE/RMSE by turbine and 1–24/25–48-hour horizon, counts missing actuals, and retains all issue/lead pairs. MAPE is not provided because zero-generation hours make it unsuitable. The present dashboard does not display actuals; add those routes/fields with the frontend owner when implementing comparisons.

Station aggregation must use physical power or confirmed capacity weights. The UI's mean of normalized turbine predictions is **not** station MW or energy.

## Persistence and jobs

The starter uses one SQLite table with typed JSON payloads. Each operation uses its own connection. Snapshot IDs cannot be overwritten through the API. Run events/results survive restart; unfinished jobs are marked failed on startup. This is designed for a single local API worker. Move work to a persistent queue before adding distributed workers or expensive training.

`/models/train` is synchronous for the small baseline. Preserve its response contract or coordinate a versioned asynchronous job change before introducing long-running ML training.

## Checks

```sh
uv run pytest tests/test_api.py tests/test_ml.py
npm run contracts
npm run check
```

After contract edits, inspect both generated files and the frontend build. Add tests for every new temporal feature and model registry implementation.
