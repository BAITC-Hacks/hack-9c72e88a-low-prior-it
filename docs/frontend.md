# Frontend owner handoff

Branch: `frontend`. Stack: React, TypeScript, Vite, plain CSS; no hosted UI or map service is required for the starter.

The dashboard uses the [wind operations theme](frontend-theme.md): navy surfaces, Inter typography, cyan accents, and a chart-first operational layout. Reuse its tokens for the future globe screen.

## Integration contract

`src/generated/api.ts` is generated from the backend OpenAPI schema. Do not edit it manually. `src/api.ts` owns request handling and exports typed API functions. Components use those functions and display the backend's error message.

Development runs on `127.0.0.1:5173`, with `/api` and `/health` proxied to `127.0.0.1:8000`. `BACKEND_URL` in the root `.env` changes the proxy target. There is no CORS requirement for this arrangement. Production needs an equivalent reverse proxy.

POSTing a forecast/replay returns a queued job with HTTP 202. Poll the corresponding GET endpoint until `succeeded` or `failed`. Read `run.error` on failure. Never display a previous run's predictions under a new issue time or model label. Each chart labels the stored request, not the live form.

The starter refresh endpoint returns `{changed, run}`. If unchanged, keep the current run. If changed, poll the new ID. An update does not overwrite the original run.

## Existing screens

- Turbine selection and missing-coordinate/capacity status.
- Issue time in UTC, 24/48-hour horizon, demo/archive source, model selector.
- Chart, accessible hourly table, CSV export, provenance/limitations.
- Agent events, run errors, recent-run selection.
- UTC February replay without actuals attached; clearly unavailable accuracy metrics.
- An observations selector for replay, with per-turbine and per-horizon MAE/RMSE when actuals match.
- A weather panel synchronized to the selected forecast hour, a persistent hourly table, and a station-coordinate schematic with an empty state for unconfigured locations.

## Next tasks

1. Keep feature components and API state separate as screens grow (`components/` and `useDashboard.ts`).
2. Add dataset upload/training using the existing routes; replay already supports selecting imported actuals.
3. Add forecasts versus actuals and metrics from the agreed contract.
4. Integrate the globe and geographic basemap after coordinates are confirmed; include map attribution.
5. Add calibrated uncertainty when the backend provides it; avoid invented shaded confidence bands.
6. Add browser tests for forecast creation, failure display, export, history, and mobile navigation.

Keep normalization visible: percentages represent the agreed `[0,1]` target contract. Do not label the mean normalized value as total station output. All starter timestamps are UTC; add local display only with an explicit timezone label. Synthetic/demo results must stay visibly labelled in charts and exports.

## Checks

```sh
npm run dev:web
npm run typecheck
npm run build
```

The generated contract is committed, so frontend build/typechecking works without a running backend. Interactive development requires the API, which already provides a complete demo path.
