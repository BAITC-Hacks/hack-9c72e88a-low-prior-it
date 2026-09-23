# Weather-SCADA model selection and January comparison

The selected weather-SCADA model achieves January **MAE 0.161806** and
**RMSE 0.233276**, compared with MAE 0.266564 for climatology and 0.268165 for
the training median. Its MAE is 39.30% lower than the strongest simple baseline
on 2,784 matched pairs. This is an observed comparison under the protocol below,
not a February score or a guarantee of operational accuracy.

This experiment compares five models on identical January issue/target pairs:
the training median, turbine-by-UTC-hour climatology, persistence, the previous
compact SCADA configuration, and a CatBoost model using forecast weather and
SCADA. Results are provisional because historical weather availability is
schedule-assumed and the bundled ECMWF archive includes hindcasts.

The authoritative numerical record is
[model-selection-results.json](model-selection-results.json). February has no
observed generation, so no February accuracy score is reported.

## Frozen chronological protocol

Only ECMWF **00 UTC** cycles are admitted. Training, development, January, and
February all issue forecasts at **12:00 UTC**: 17:00 Kazakhstan civil time
(UTC+5) or 18:00 on the fixed UTC+6 source SCADA clock. These clocks are distinct.
The publication assumption is `run_init + 10h`; weather run leads 13–60 cover
power targets T+1 through T+48 without extrapolation.

Training origins begin March 15, 2024 at 12:00 UTC. Expanding development folds
use cutoffs November 1 and December 1, 2025 at 00:00 UTC, with daily issues
November 1–28 and December 1–29 at 12:00 UTC. Three fixed weather configurations
are compared. Selection minimizes sample-weighted development MAE, then RMSE,
then candidate name. January does not select parameters or extra features.

The January model is trained through **January 1, 2026 at 00:00 UTC**. Evaluation
issues run January 1–29 at 12:00 UTC with 48-hour horizons. Training targets and
their availability respect the training cutoff. At prediction, SCADA features
respect each issue time; the numerical forecast comes from the model, not LLM
text. Forecast weather is selected by run and availability before issue time.
Incomplete weather origins are counted and skipped during training; inference
continues to require the entire forecast horizon.

Constant and climatology use only training-period observations available by
January 1. Their statistics remain fixed through evaluation. Climatology is the
median for each turbine and UTC target hour; the constant is the overall training
median. Persistence uses the latest observation available at each issue time.
The SCADA comparator retains the earlier compact MAE hyperparameters, refitted
on the same training start and daily origins.

## January metrics

| Model | Scored pairs | MAE | RMSE |
| --- | ---: | ---: | ---: |
| Constant (training median) | 2,784 | 0.268165 | 0.345056 |
| Climatology | 2,784 | 0.266564 | 0.342370 |
| Persistence | 2,784 | 0.337667 | 0.459336 |
| CatBoost SCADA | 2,784 | 0.312239 | 0.389328 |
| CatBoost weather-SCADA | 2,784 | 0.161806 | 0.233276 |

### Turbine and lead-window breakdown

| Model | Turbine | Leads | Scored pairs | MAE | RMSE |
| --- | --- | --- | ---: | ---: | ---: |
| Constant (training median) | turbine-1 | 1-24 | 696 | 0.267000 | 0.343039 |
| Constant (training median) | turbine-1 | 25-48 | 696 | 0.271205 | 0.349189 |
| Constant (training median) | turbine-2 | 1-24 | 696 | 0.264677 | 0.340267 |
| Constant (training median) | turbine-2 | 25-48 | 696 | 0.269780 | 0.347655 |
| Climatology | turbine-1 | 1-24 | 696 | 0.266716 | 0.339220 |
| Climatology | turbine-1 | 25-48 | 696 | 0.270576 | 0.344885 |
| Climatology | turbine-2 | 1-24 | 696 | 0.262020 | 0.339155 |
| Climatology | turbine-2 | 25-48 | 696 | 0.266946 | 0.346159 |
| Persistence | turbine-1 | 1-24 | 696 | 0.298518 | 0.427847 |
| Persistence | turbine-1 | 25-48 | 696 | 0.377991 | 0.488449 |
| Persistence | turbine-2 | 1-24 | 696 | 0.296358 | 0.427696 |
| Persistence | turbine-2 | 25-48 | 696 | 0.377802 | 0.489284 |
| CatBoost SCADA | turbine-1 | 1-24 | 696 | 0.282757 | 0.358109 |
| CatBoost SCADA | turbine-1 | 25-48 | 696 | 0.334378 | 0.410842 |
| CatBoost SCADA | turbine-2 | 1-24 | 696 | 0.285018 | 0.363045 |
| CatBoost SCADA | turbine-2 | 25-48 | 696 | 0.346801 | 0.421274 |
| CatBoost weather-SCADA | turbine-1 | 1-24 | 696 | 0.137304 | 0.197546 |
| CatBoost weather-SCADA | turbine-1 | 25-48 | 696 | 0.185005 | 0.261565 |
| CatBoost weather-SCADA | turbine-2 | 1-24 | 696 | 0.138281 | 0.202260 |
| CatBoost weather-SCADA | turbine-2 | 25-48 | 696 | 0.186636 | 0.263288 |

Weather-SCADA MAE is 39.30% lower than climatology, the strongest
simple baseline, and 39.66% lower than the constant. It also improves
on the SCADA comparator by 48.18%. The SCADA comparator loses to the
constant under this noon protocol; that result is retained. Weather-SCADA wins
MAE and RMSE in each of the four turbine/lead cells in this comparison.

Every model scores **2,784 pairs**, with
**0 missing actual targets**. The common pair fingerprint is
`620458340613ef6ef102783786db670a96f589ae06465b54cf5cbb67afa575a4`.

The constant is 0.226667, fitted from
29,462 training-period observations.
The old midnight, longer-history SCADA score is not directly comparable to
this new noon protocol; both SCADA and weather models have been refitted here.

The five-model tables are generated from the completed experiment report, with
identical scored-pair hashes and turbine/lead coverage. MAE and RMSE are errors
on normalized power [0,1], not accuracy percentages. Pooled MAE weights samples;
pooled RMSE takes the root of the pooled squared errors. Overlapping forecasts
are separate correlated issue/target pairs, not independent trials.

## Development selection

| Candidate | November MAE | December MAE | Pooled MAE | Pooled RMSE |
| --- | ---: | ---: | ---: | ---: |
| weather-compact-mae | 0.155675 | 0.193860 | 0.175006 | 0.258686 |
| weather-depth6-mae (selected) | 0.154157 | 0.194738 | 0.174701 | 0.256855 |
| weather-depth6-rmse | 0.172775 | 0.205725 | 0.189456 | 0.248038 |

Selected: **weather-depth6-mae**, 500 trees, depth 6,
learning rate 0.04, MAE loss, L2 10, seed 42,
daily origins and weather-SCADA features. No extra feature search on January was performed.
The RMSE candidate has lower pooled development RMSE but loses the predeclared MAE objective.
The selected candidate also loses December MAE to the compact candidate; the
selection criterion pools both development folds rather than choosing one month.

Each candidate scores 2,688 November pairs and 2,756 December pairs,
5,444 in total. December has 28 missing actual targets; candidates have identical
coverage and pair fingerprints.

| Model stage | Turbine | Training pairs | Missing/late targets | Weather origins skipped |
| --- | --- | ---: | ---: | ---: |
| january | turbine-1 | 27,854 | 3,346 | 5 |
| january | turbine-2 | 30,446 | 754 | 5 |
| refit | turbine-1 | 29,294 | 3,346 | 5 |
| refit | turbine-2 | 31,886 | 754 | 5 |

The five weather skips per turbine are August 5-9, 2025: four missing run dates
and one run with empty required weather. They do not become synthetic training
examples. The January weather fit has 58,300 pairs; the final refit has 61,180.
Missing/late target counts apply to otherwise weather-eligible training origins.

The development table reports each fixed candidate, both chronological folds,
and pooled errors. A lower January score never changes the development winner.
The explicit hyperparameter plan, sample counts, training skips, and source
fingerprints are retained in the JSON record.

## Final refit and February artifact

The chosen weather configuration is refitted through **January 31, 2026 at
12:00 UTC**. Its weights are distinct from the January evaluation model.
January metrics must not be assigned to this later refit.

`npm run reproduce` generates and registers native weights locally, verifies
their file and prepared-history checksums when loading, imports archive snapshots,
and runs `WindService.execute_backtest` / `ForecastAgent`, the same path used
by the API. A saved evidence JSON alone does not imply that local weights exist.

[results/february-2026/forecast.csv](../results/february-2026/forecast.csv) retains
every target for 29 daily issues from January 31 through February 28 at 12 UTC:
two turbines × 48 hours × 29 issues = **2,784 rows**. Boundary targets in January
and March are retained. The API's February-period CSV separately filters valid
times to `[2026-02-01, 2026-03-01)`.

The [manifest](../results/february-2026/manifest.json) records the model, parameters,
input and forecast checksums, versions, issue schedule, selected snapshots,
and assumptions. Weather is from the bundled archive, with no synthetic weather.
No February actuals are supplied and no February metrics are invented. As
January SCADA ages, forecast features retain that aging history without synthetic
February observations.

## Reproduction and live verification

```sh
uv sync --locked
npm ci
npm run reproduce
npm run check
npm run dev
```

With the API and frontend running, in another terminal:

```sh
uv run python scripts/smoke_demo.py --archive
```

The smoke check selects the registered weather-SCADA refit, runs a noon archive
forecast, verifies unchanged-input refresh, replays all 29 daily issues, and
checks CSV export. Without `--archive`, the script deliberately uses a synthetic
demonstration. Neither smoke mode estimates prediction accuracy.

In the dashboard, select the registered `catboost-weather-scada-v1` model,
archive weather, January 31 at 12:00 UTC, and a 48-hour horizon. Reproduction
prints the model identifier; IDs should be obtained from the local registry,
not copied from a different machine's database.

## Provenance and limits

- Open-Meteo describes the early ECMWF archive as IFS 49R1 hindcasts. This is a
  reconstruction, not independently proven contemporaneous operational output.
- The **10-hour publication delay is an assumption**, conservatively derived
  from the published ECMWF dissemination schedule. It is not observed per-run
  availability or proof of the schedule for every historical date. The research
  importer records this explicitly; API and worker candidates remain unverified.
- Timestamp and model-cutoff guards remain strict. No observed future weather,
  reanalysis, future SCADA features, or synthetic substitute is used to fill
  unavailable forecast inputs.
- SCADA uses the fixed UTC+6 source clock, interval-start raw readings and
  hourly interval-end labels. Reporting latency is assumed to be 10 minutes.
  Physical normalization, rated capacities and hub height remain provisional or
  unknown; wind at 100 m is the feature height, not a supplied hub height.
- January was previously inspected and remains a reused comparison period,
  not a pristine holdout. Two development folds and two turbines cannot establish
  all-season superiority, significance, or calibrated uncertainty.
- February accuracy is unknown. Meeting timestamp inequalities does not resolve
  the competition's stronger requirement to prove historical forecast availability.

Sources and detailed import semantics: [weather-archive.md](weather-archive.md).
