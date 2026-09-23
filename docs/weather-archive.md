# ECMWF archive import and availability assumption

The reproduction uses the bundled Open-Meteo Single Runs ECMWF IFS data as a
**hindcast reconstruction with schedule-assumed availability**. It does not prove
which exact forecasts a user could obtain on each historical issue date. This is
a material limitation against the competition's strict historical-availability
requirement, even though the replay enforces all timestamp and cutoff checks.

## Source and publication policy

[Open-Meteo's Single Runs documentation](https://open-meteo.com/en/docs/single-runs-api)
identifies ECMWF data beginning March 14, 2024 as IFS Cycle 49R1 hindcasts. The
bundled March 2024–February 2026 period belongs to this early archive. Do not call
it independently verified contemporaneous operational output. Its initialization
time describes the model run, not the historical release of its reconstructed
values. No reanalysis or measured future weather is substituted by this import.

The [ECMWF dissemination schedule](https://confluence.ecmwf.int/pages/viewpage.action?pageId=600793086)
reviewed on September 23, 2026 lists 00 UTC atmospheric fields through forecast
hour 90 at 05:45–06:12 UTC, and the final longer-range fields by 07:34 UTC.
[ECMWF Open Data](https://www.ecmwf.int/en/forecasts/datasets/open-data) says IFS data
are released at the end of dissemination. We choose
`ECMWF_PUBLICATION_DELAY_HOURS = 10`: `available_at = run_init + 10h`, providing
2h26m after that published final time. This buffer is a project assumption for
reconstruction, not a measured per-run delay or historical API service guarantee.
The current schedule is not proof that the same schedule applied throughout
2024–2026; outages and original download times were not recorded.

Only the separate offline importer can opt in to this assumption. By default it
produces `verification="unverified"` candidates with `available_at=null`. With
`--accept-schedule-assumption`, it writes `verification="verified"` to satisfy
the existing archive contract, with a mandatory evidence string explicitly
recording the source, run initialization, file checksum, schedule, hindcast
limitation, and lack of per-run historical proof. Here that enum means acceptance
of the disclosed research protocol; it does **not** strengthen the evidence.
The API downloader and worker continue to create unverified candidates.

## Time and variable mapping

Training, development folds, January comparison, and February replay all use
only **00 UTC runs** and issue forecasts daily at **12:00 UTC**. This is **17:00
Kazakhstan civil time (UTC+5)** during the evaluated period, or **18:00 on the
fixed UTC+6 source SCADA clock** accepted for this dataset. The two clocks are
different; source timestamps are not relabeled as civil time.

At 12 UTC the +10h publication assumption has elapsed. Targets T+1 through T+48
use run leads 13–60, all within the supplied 0–71 range. Issuing at midnight
would require an unavailable new run or the missing lead 72 of the previous run.

| CSV field | Contract field | Semantics |
| --- | --- | --- |
| `run_utc` | `run_init` | UTC initialization; 00 UTC only |
| `loc` | `turbine_id` | 1 → turbine-1; 2 → turbine-2 |
| `valid_utc` | `WeatherPoint.valid_time` | UTC hour unchanged |
| `wind_speed_100m` | `wind_speed_ms` | m/s, height 100 m |
| `wind_direction_100m` | `wind_direction_deg` | degrees at 100 m |
| `temperature_2m` | `temperature_c` | Celsius at 2 m |

`windagent/openmeteo.py:fetch_single_run` requests `wind_speed_unit=ms` and
`timezone=GMT`; the default temperature unit is Celsius. The compiled CSV does
not contain the original `hourly_units` objects, so this is collector-based unit
evidence, not a retained metadata check for every response. `lead_h` must exactly
equal `(valid_utc - run_utc)` in hours; duplicate hours, invalid locations,
non-finite or physically invalid values are rejected.

Power labels are hourly interval ends. Weather at that same UTC endpoint is
used as a covariate for mean power over the preceding hour; it is not claimed to
be an observed hourly mean. No extra +1h shift is applied to weather. The
`retrieved_at` value records local import time, not a fabricated past retrieval.
Both nearby turbines share a numerical-weather grid cell. Their power models
still have separate turbine identities; 100 m is the weather-feature height,
not a supplied turbine hub height.

## Completeness and repeatability

The tracked gzip has SHA-256
`7b9a425c47be656834545ad32c17307fd739680952bb4fb5ec9fe253125597a3`.
It contains 806 cycles / 116,064 rows including later 06/12/18 UTC cycles. The
00 UTC selection has 713 dates and 1,426 turbine/run groups. August 5, 6, 8 and 9,
2025 are absent; August 7 exists but both turbines have 72 missing required
weather rows. The importer skips those two empty groups and reports **1,424
snapshots / 102,528 valid points**. Every January 31–February 28, 2026 daily run
has all 48 required target hours for both turbines. Missing values are never
imputed from observations or from a different cycle.

Snapshot IDs include the protocol version, source checksum and assumption mode; repeated API imports
retain the existing immutable snapshot instead of overwriting provenance.
Changes to the input gzip produce new IDs. The import metadata captures counts,
missing dates, sources, units, checksum, assumptions, and limitations.

```sh
# Safe default: export candidates locally; no API or network required.
uv run python scripts/import_weather_archive.py --output artifacts/weather-candidates.json

# Explicit documented research import into a running backend.
uv run python scripts/import_weather_archive.py --accept-schedule-assumption
```

Python callers use `wind_agent.ecmwf_archive.import_ecmwf_archive(...)`, receiving
`.snapshots` and `.metadata`. Start/end boundaries must have explicit timezones;
the end is exclusive. Full reproduction passes the explicit assumption flag and
records `.metadata` in the final manifest. It cannot turn hindcasts or a modern
dissemination schedule into contemporaneous publication evidence.
