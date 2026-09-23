# February 2026 forecast reconstruction

`forecast.csv` contains 29 daily issues (31 January–28 February, 12:00 UTC / 17:00 Asia/Almaty), two turbines and 48 hourly targets per turbine: 2,784 rows. All horizon rows are retained, including January/March boundary targets.

The refitted CatBoost weather-SCADA model runs through the same `WindService.execute_backtest` / `ForecastAgent` path as the API. Weather comes exclusively from bundled ECMWF 00 UTC runs, with 100 m wind. No synthetic weather or February observed power is used.

**Provisional hindcast reconstruction, not proven historical operational availability.** Publication is assumed at run initialization + 10 hours. Open-Meteo documents early ECMWF runs as IFS 49R1 hindcasts; the published dissemination schedule does not prove availability of each archived run. See [provenance](../../docs/weather-archive.md).

`manifest.json` records checksums, model parameters, versions, each selected snapshot and assumptions. Power is a normalized fraction [0,1], not MW. February actuals are unavailable: metrics are intentionally empty.

Rebuild from the repository root with `npm run reproduce`. Verify with `uv run python scripts/run_tests.py`.
