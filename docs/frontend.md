# Frontend owner handoff

Branch: `frontend`. Stack: React, TypeScript, Vite, plain CSS; no hosted UI or map service is required for the starter.

The dashboard uses the [operations theme](frontend-theme.md): navy surfaces, Inter typography, cyan accents, and a chart-first forecast layout. Explore shares the same tokens. Profile appearance settings offer General, Light, and Black, remembered locally.

## Integration contract

`src/generated/api.ts` is generated from the backend OpenAPI schema. Do not edit it manually. `src/api.ts` owns request handling and exports typed API functions. Components use those functions and display the backend's error message.

Development runs on `127.0.0.1:5173`, with `/api` and `/health` proxied to `127.0.0.1:8000`. `BACKEND_URL` in the root `.env` changes the proxy target. There is no CORS requirement for this arrangement. Production needs an equivalent reverse proxy.

POSTing a forecast/replay returns a queued job with HTTP 202. Poll the corresponding GET endpoint until `succeeded` or `failed`. Read `run.error` on failure. Never display a previous run's predictions under a new issue time or model label. Each chart labels the stored request, not the live form.

The starter refresh endpoint returns `{changed, run}`. If unchanged, keep the current run. If changed, poll the new ID. An update does not overwrite the original run.

## Existing screens

- Globe Explore: country search/picking, energy-type filters, explicit site grouping, turbine selection, and forecast handoff. See [Explorer](explorer.md).
- Profile appearance menu, with persistent General / Light / Black themes.
- Turbine selection and missing-coordinate/capacity status.
- Issue time in UTC, 24/48-hour horizon, demo/archive source, model selector.
- Chart, accessible hourly table, CSV export, provenance/limitations.
- Agent events, run errors, recent-run selection.
- UTC February replay, with clearly unavailable accuracy metrics when actuals are not attached.
- An observations selector for replay, with per-turbine and per-horizon MAE/RMSE when actuals match.
- A weather panel synchronized to the selected forecast hour, a persistent hourly table, and a station-coordinate schematic with an empty state for unconfigured locations.
- Canonical CSV/JSON dataset import with provenance, binned/persistence/ridge/CatBoost training, and verified-weather management in expandable panels.
- Actual-observation overlays from the inclusive observation-window API; hollow circles distinguish measurements from predictions and synthetic datasets remain labelled.

## Next tasks

1. Keep feature components and API state separate as screens grow (`components/` and `useDashboard.ts`).
2. Refine dataset upload/training feedback; these controls and the replay actuals selector are implemented.
3. Expand forecasts-versus-actuals inspection and metrics using the agreed contract.
4. Extend the explorer with additional registered sites and a detailed local basemap if needed. The current world/country layer includes Natural Earth attribution.
5. Add calibrated uncertainty when the backend provides it; avoid invented shaded confidence bands.
6. Add browser tests for forecast creation, failure display, export, history, and mobile navigation.

Keep normalization visible: percentages represent the agreed `[0,1]` target contract. Do not label the mean normalized value as total station output. All starter timestamps are UTC; add local display only with an explicit timezone label. Synthetic/demo results must stay visibly labelled in charts and exports.

## Checks

```sh
npm run dev:web
npm run typecheck
npm run test --workspace frontend
npm run test:flow --workspace frontend
npm run build
```

The generated contract is committed, so frontend build/typechecking works without a running backend. Interactive development requires the API, which already provides a complete demo path.

`test` runs the station/catalog checks plus the component flow suite. `test:flow` runs the Vitest/jsdom tests in `tests/flow/`: country/turbine selection through forecast results, Back navigation, invalid URLs, refresh/reconnect, keyboard focus, replay history, configured weather turbine IDs, and profile appearance. These tests mock HTTP and disable WebGL; they do not verify globe rendering, mobile layout, or real browser behavior. API integration tests and `scripts/smoke_demo.py` exercise the backend separately.

Workspace feedback stays visible in both Explore and Forecast. Header refresh reloads the registry and forecast workspace, while completed/failed replays automatically refresh the saved forecast list (up to 100 recent runs) without replacing the selected run or edited controls. February replay uses its fixed January 31 origin independently of the single-forecast issue-time input.
