# Team plan (original implementation responsibilities)

Optional cloud analysis: [OpenAI setup](docs/openai-agent.md) or [NVIDIA setup](docs/nvidia-agent.md).
It explains completed forecasts using read-only tools; numerical prediction remains
with the selected ML model. Installing dependencies does not restore trained weights
or model registry records in a fresh clone.

### Person 1 — Agent / weather / orchestration (`Agent` branch)

**Own:** `agent/`, `tests/test_leakage.py`, `tests/test_weather_adapter.py`, `docs/agent.md`.

**Already provided:** `ForecastAgent`, weather/predictor protocols, deterministic demo weather, verified-archive selection, a Single Runs download adapter, bounded retries, input fingerprints, decision events, and an optional refresh watcher.

**Your tasks, in order:**

1. Confirm both coordinates and investigate original forecast coverage for January–February 2026. Record the source, original model run, publication evidence, units, and wind height.
2. Download candidate weather through `/weather/fetch`; verify provenance before importing a separate verified snapshot. A current download timestamp is not historical publication evidence.
3. Complete weather preparation: choose a suitable model/height, handle missing hours explicitly, cache raw provider responses, and document any correction or interpolation.
4. Improve the agent's decisions: choose permitted fallback runs, explain failures, monitor new inputs, and recompute when the fingerprint changes.
5. Evaluate the optional OpenAI/NVIDIA analyst reports. The forecast workflow enforces data availability deterministically; the LLM explains completed results through read-only tools and cannot change power values or verify weather archives.

**Deliver to backend:** a `WeatherProvider` returning `WeatherSnapshot`; `ForecastAgent.run(request, turbines, emit)` returns `ForecastResult`. Import only `wind_contracts`, your own code, and third-party libraries. Do not import backend implementation modules.

**Done when:** both turbines have evidence-backed forecast snapshots, replay cannot see future weather, failures/retries are logged, changed inputs produce a new run, and your tests pass.

### Person 2 — Backend / ML / evaluation (`backend` branch)

**Own:** `backend/`, `tests/test_api.py`, `tests/test_ml.py`, data adapters in `scripts/`, `docs/backend.md`.

**Steward shared integration files:** `contracts/`, `config/`, `pyproject.toml`, `uv.lock`, root scripts and CI. Discuss breaking contract changes with the other two people in the PR; no separate permission process is required.

**Already provided:** versioned FastAPI routes, validated schemas, SQLite storage, dataset import, a trainable binned power-curve baseline, an illustrative demo model, forecast/backtest jobs, horizon-specific MAE/RMSE, exports, and restart recovery.

**Your tasks, in order:**

1. Obtain the supplied March 2023–January 2026 data. Confirm source columns, timestamp semantics, timezone changes, turbine IDs, and normalization. Convert it to the canonical observation contract.
2. Analyse missing values, curtailment/stoppages, invalid readings, and target distribution. Fit transformations on training data only.
3. Implement a persistence baseline and a candidate ML model behind `Predictor`. The included binned curve is a starting baseline, not a validated final solution.
4. Join archived weather to targets by **issue time + valid time + turbine**, not just timestamp. Add forecast lead, weather variables, and only those SCADA features available at issue time.
5. Use chronological pre-February validation. Freeze model selection before scoring February. Add calibrated uncertainty only after checking coverage.
6. Produce February CSVs and a metrics report, separately for 1–24 and 25–48 hours and each turbine. Add station-level aggregation when rated capacities and normalization are confirmed.

**Deliver to agent:** a `Predictor` with `.info` and `.predict(turbine, weather, issued_at) -> list[ForecastPoint]`. **Deliver to frontend:** the API in section 4 and generated types. Keep ML independent of HTTP.

**Done when:** training is reproducible, model metadata records cutoff/data/version, no feature uses future observations, replay metrics beat or honestly compare with baselines, and API tests pass.

### Person 3 — Frontend / demonstration (`frontend` branch)

**Own:** `frontend/` except generated contracts, `docs/frontend.md`; update the npm lockfile when dependencies change.

**Already provided:** React + TypeScript + Vite, typed API client, turbine selection, 24/48-hour controls, normalized-power chart and table, asynchronous job polling, errors, provenance, decision log, history, replay, and CSV downloads.

Also integrated: canonical CSV/JSON upload, source provenance, all four model-training choices, observation overlays, candidate weather download, and immutable snapshot import. Expand **Datasets & model training** or **Weather archive** below the replay panel.

**Your tasks, in order:**

1. Refine the dashboard and add a map once coordinates are confirmed.
2. Build dataset upload/training controls on the existing routes; add a selector for actual observations in replay. Until then, use Swagger or the CSV helper.
3. Display forecast versus actual power, per-horizon metrics, and missing-data coverage. Show uncertainty only when supplied by a calibrated backend model.
4. Make archive verification status and original issue times visible. Keep demo results clearly labelled.
5. Polish loading, empty, error, keyboard, and mobile states; prepare a short demonstration of the full workflow.

**Integration rule:** all calls go through `frontend/src/api.ts`. Import generated types from `frontend/src/generated/api.ts`; do not recreate response shapes or calculate power predictions in the browser.

**Done when:** users can launch and inspect a forecast/replay, errors are understandable, the UI shows real API data and correct units, and `npm run build` passes.

