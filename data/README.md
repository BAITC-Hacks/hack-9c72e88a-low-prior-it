# Local data

This directory holds the SQLite database and raw/processed datasets. The branch consolidation preserves the already tracked `raw/turbine_1.csv`, `raw/turbine_2.csv`, and three compressed candidate weather archives under `weather/`. Other local data, database files, caches, and generated outputs remain ignored.

The candidate archives are available for offline analysis with `windagent/`; they are not automatically approved or imported into the forecasting API. Strict replay still requires original publication evidence. See [DATA.md](../DATA.md) for the inherited analysis and [data/replay contracts](../docs/data-and-replay.md) for the API's UTC interval-end rules. Record source lineage, timezone conversion, normalization, and checksums when preparing canonical data. Use `examples/` for explicitly artificial development inputs.
