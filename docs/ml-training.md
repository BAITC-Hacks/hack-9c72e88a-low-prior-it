# Local training and validation

The repository now supports `binned-power-curve`, `persistence`, and `catboost`
through the existing `POST /api/v1/models/train` endpoint. The default remains the
original binned curve for compatibility. No API key or NVIDIA service is needed.
CatBoost runs on CPU, one estimator per turbine, with a fixed seed and bounded
iterations/depth. Model selection uses earlier chronological folds; no search or
early stopping is performed on the January comparison period.

## Source data and assumptions

`dataset/turbine1.csv` and `dataset/turbine2.csv` are organizer SCADA files. The
adapter maps their Russian headers explicitly. Source files are never edited and
`dataset/` is ignored by Git. Prepared data belongs in `data/prepared/`.

The current files contain 142,360 and 149,499 readings, from March 11, 2023 through
January 31, 2026 in the source clock. No February actuals or verified archived weather
forecasts are available. Candidate weather CSVs merged from main remain unverified;
see [DATA.md](../DATA.md). Values fall within the existing normalized-power contract
of [0,1], but the physical normalization definition is not confirmed.

The user confirmed **fixed UTC+06:00** and timestamps at the **start** of each
10-minute interval. The current revision applies that fixed offset to the entire
history, then adds 10 minutes to obtain the canonical interval-end timestamp. It
does not follow the historical civil-time changes of `Asia/Almaty`.

The experiment remains **provisional** because observation latency and the physical
normalization definition are unknown. It assumes readings become available 10 minutes
after interval end and uses the source power values unchanged in [0,1]. These two
assumptions still require confirmation before competition scoring.

Revision `almaty-provisional-v1` and its models used superseded time assumptions.
Keep them for audit only. The current revision `utc6-start-provisional-v2` does not
quarantine any rows: the fixed offset has no ambiguous local hour. IANA timezone
support remains available for other datasets; ambiguous/nonexistent civil times
are still rejected unless explicitly quarantined.

```powershell
.\.venv\Scripts\python.exe scripts/prepare_dataset.py --input-dir dataset --output data/prepared/utc6-start-provisional-v2 --timezone UTC+06:00 --timestamp-position start --latency-minutes 10 --provisional --time-semantics-confirmed
```

The command refuses to overwrite an existing output directory. It produces:

- `observations.csv`: only complete hourly means, compatible with the existing importer;
- `hourly_statistics.jsonl`: statistics and sample counts, including partial hours;
- `preparation.json`: source checksums, assumptions, quarantine and coverage reports.

No missing readings are replaced with zero. No out-of-range values are silently
clipped during ingestion. The corrected revision has 23,667 complete hours for turbine
1 and 24,785 for turbine 2 (48,452 total). Partial hours are excluded from model targets.

## First real-data experiment

```powershell
.\.venv\Scripts\python.exe scripts/train_evaluate.py --prepared data/prepared/utc6-start-provisional-v2 --trained-through 2026-01-01T00:00:00Z --first-origin 2023-04-01T00:00:00Z --last-origin 2025-12-29T00:00:00Z --validation-start 2026-01-01T00:00:00Z --validation-end 2026-01-28T00:00:00Z --iterations 300 --depth 6 --register
```

Run from the repository root. The Python dependencies are declared in
`pyproject.toml` and locked in `uv.lock`; use `uv sync --locked` for a fresh setup.
The initial Windows run uses Python 3.13 from `.venv`. No localhost server is
required for this command. `--register` writes new immutable dataset/model IDs to
the local API database; omit it for an experiment isolated from the API.

Training origins are daily and include leads 1..48. Both target time and target
availability must be no later than the training cutoff. Missing/late targets are
counted in the report, not filled. The last training target must precede validation.
The model is fitted once; validation does not refit it. All dates in the command
are UTC, and all validation targets precede February.

At each validation origin the predictor can use SCADA that has already become
available, including earlier January observations. It cannot use that origin's
future measurements. The full observation history is stored as an immutable source
dataset, with a checksum; storing future rows does not make them eligible features.
Persistence and CatBoost are scored on exactly the same turbine/issue/target pairs.
Their metrics use the same [0,1] power scale; MAE 0.05 means 5 percentage points.

The command prints new model IDs and creates `artifacts/experiments/experiment-*/`:

- `report.json`: MAE/RMSE and sample counts per turbine and 1–24 / 25–48-hour horizon,
  missing actuals, model parameters, feature importance, and preparation provenance;
- `predictions.csv`: separate algorithm/issue/lead predictions, preserving overlap.

Native CatBoost `.cbm` files and their manifest are stored under
`artifacts/models/model-*/` when registered. Reload checks feature version, source
history checksum and model-file checksums. Evaluation uses the reloaded estimator.
The manifest records CatBoost version, random seed, parameters, feature names,
training window and archived weather lineage when relevant.

Until the source assumptions are confirmed, `--provisional` maps to the existing
`is_demo=true` safety label on imported models. The rows are real SCADA, but the
result must not be represented as a verified competition score.

## Forecast features

`feature_set="scada"` is the initial CatBoost baseline and requires no weather:
cyclic target hour/day, lead, latest available power/wind/temperature, observation
age, and trailing 3/6/24-hour mean/std/count. Every lead shares the same origin-safe
SCADA context. Empty rolling windows remain missing, with zero counts, rather than
being interpreted as zero power. Features are built identically during training
and prediction. CatBoost numeric outputs are explicitly bounded to [0,1] within
the numerical predictor; the agent and any future LLM do not alter them.

`feature_set="scada-extended"` adds exact origin-relative lags at 1/2/3/6/12/24/48/72/168
hours, trailing 48/168-hour mean/std/min/max/count, and changes over 3/24 hours.
Absent or late lag readings remain missing; a row shift must never bridge a missing
clock hour. All features use both event time and availability time. This mode has
its own feature version, so existing `scada` and `weather-scada` artifacts still load.

`feature_set="weather-scada"` additionally consumes forecast wind speed, cyclic
wind direction and temperature from existing `WeatherSnapshot` contracts. It
requires complete, verified historical forecasts published by each origin. Missing
archives cause an explicit failure. Future measured wind is never substituted.
The training routine records which snapshot was used at each origin. For offline
experiments supply `--feature-set weather-scada --weather path/to/snapshots.json`
where the JSON is an array of existing `WeatherSnapshot` objects.

The SCADA-only model is a baseline for 24–48 hours, not a substitute for the task's
required weather integration. Pressure/humidity/precipitation are not yet in the
weather contract. Add these only when the weather provider supplies verified data.

## Swagger training and forecasts

The existing demo training request still works. To choose persistence, add
`"algorithm": "persistence"`. To train CatBoost on an imported real-data dataset:

```json
{
  "dataset_id": "dataset-REPLACE",
  "algorithm": "catboost",
  "feature_set": "scada",
  "trained_through": "2026-01-01T00:00:00Z",
  "first_origin": "2023-04-01T00:00:00Z",
  "last_origin": "2025-12-29T00:00:00Z",
  "horizon_hours": 48,
  "iterations": 300,
  "depth": 6,
  "learning_rate": 0.05,
  "random_seed": 42
}
```

Training remains a synchronous local endpoint. For longer runs prefer the CLI;
do not repeatedly click Train while a request is running. Each run gets a new ID.
The 12-row example is intentionally too small for the CatBoost training guard.

Registered models appear in `GET /api/v1/models` and use the existing
`POST /api/v1/forecasts` contract. The existing agent still fetches weather. With
SCADA-only models the values are ignored, and an explicit warning is returned.
`weather_source="demo"` exercises the API/UI but remains labelled demo.
The offline evaluation command does not synthesize weather for SCADA-only models.

For official February scoring use verified archive snapshots and confirmed data
semantics. Current data stops in January, so February MAE/RMSE cannot be computed.
Do not feed February actuals back into training or features without an explicit
evaluation policy permitting that information at the relevant origins.

## Chronological model selection

```powershell
.\.venv\Scripts\python.exe scripts/tune_model.py --prepared data/prepared/utc6-start-provisional-v2 --evaluate-january --register
```

This CPU job runs four predefined candidates on two development folds, saves the
selection, then trains the winner through January 1 and evaluates it once on daily
January 1–28 origins. `--register` applies only to this final model. Without
`--evaluate-january`, the script stops after selection. No server is required.

| Candidate | Features | Loss | Trees | Depth | Learning rate | L2 | Origin step |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | scada | RMSE | 300 | 6 | 0.05 | 3 | 24 h |
| compact-mae | scada | MAE | 500 | 4 | 0.04 | 10 | 24 h |
| extended-rmse | scada-extended | RMSE | 500 | 5 | 0.04 | 10 | 12 h |
| extended-mae | scada-extended | MAE | 500 | 5 | 0.04 | 10 | 12 h |

Development cutoffs are November 1 and December 1, 2025 at 00:00 UTC. Each fold
scores daily origins on days 1–14 of its month, leads 1..48. Training starts April
1, 2023, ends with an origin 72 hours before the cutoff, and filters labels by
availability at that cutoff. The later fold may train on the earlier fold's
observations: this is an expanding chronological window. Seed 42, two CPU threads,
no early stopping. Subdaily origins expand training only; evaluation remains daily.

The winner minimizes pooled MAE across turbine/horizon/fold samples; pooled RMSE
breaks ties. Candidate coverage must match. The unchanged baseline is eligible,
so an unhelpful new configuration cannot win merely because it is new. These
hyperparameters follow the available [CatBoost regression objectives](https://catboost.ai/docs/en/concepts/loss-functions-regression)
and [training parameters](https://catboost.ai/docs/en/references/training-parameters/common).

Each invocation creates a new `artifacts/tuning/selection-*/` directory. `plan.json`
is written before any fit; each fold retains its command, console log, model,
report and predictions. `selection.json` is written before January is evaluated;
`january.json` points to the final report. A failed subprocess stops selection and
keeps completed reports for diagnosis. Before winner selection, add
`--resume artifacts/tuning/selection-REPLACE` to continue interrupted folds under
the identical plan and commands. Completed reports are reused; retry logs and models
get new paths. No existing model artifact is overwritten.

January had already been inspected for the original baseline. It is a reused
comparison period, not a pristine unseen test set. It is excluded from this search,
and the selected configuration is not changed after its January result is known.
February remains outside all training and model selection. Overlapping 48-hour
forecasts are correlated, so sample counts are not independent-trial counts.

Individual runs also accept `--feature-set scada-extended`, `--loss-function MAE`,
`--learning-rate`, `--l2-leaf-reg`, and `--origin-step-hours 6|12|24` in
`scripts/train_evaluate.py`; the same bounded fields are available in `TrainRequest`.

After evaluation, refit the frozen winner using the registered dataset ID from
the January report:

```powershell
.\.venv\Scripts\python.exe scripts/refit_selected.py --selection artifacts/tuning/selection-REPLACE/selection.json --dataset-id dataset-REPLACE --trained-through 2026-01-31T00:00:00Z
```

This registers a separate model, checks the source history checksum, and writes
`artifacts/refits/refit-*/request.json` and `report.json`. It preserves the chosen
parameters and 72-hour training-origin gap. Earlier validation scores do not
measure these refitted weights. Issues before the new cutoff are rejected.
Results, local model IDs and a forecast request: [selected model](tuned-training-results.md).

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
```

When HTTP contracts change, regenerate OpenAPI and TypeScript and run the frontend
build. Tests cover future SCADA/labels, delayed availability, weather provenance,
chronological windows, per-turbine training, persisted-model predictions, corrupt
artifacts, historical timezone conversion, and API compatibility.
