# Chronological CatBoost selection (provisional)

January MAE improves from **0.29834 to 0.28006 (6.13%)**; RMSE improves from
**0.34067 to 0.33508 (1.64%)**. Relative to persistence, MAE is 18.49% lower.
Both metrics improve in every turbine/horizon group. This is a SCADA-only result,
not a February competition score.

## Selection before January evaluation

Four predefined configurations use expanding chronological folds: cutoffs November
1 and December 1, 2025, 00:00 UTC; daily evaluation origins on days 1–14, leads
1..48. Features and fitting labels obey their respective availability cutoffs.

| Configuration | November MAE | December MAE | Pooled MAE | Pooled RMSE |
| --- | --- | --- | --- | --- |
| Previous baseline, RMSE | 0.31192 | 0.34830 | 0.32992 | 0.36900 |
| **Compact MAE (selected)** | **0.31736** | **0.31333** | **0.31536** | **0.37310** |
| Weekly lags, RMSE | 0.31597 | 0.35847 | 0.33700 | 0.37117 |
| Weekly lags, MAE | 0.32360 | 0.34442 | 0.33390 | 0.37763 |

Pooled scores weight groups by scored samples: November 1,344; December 1,316;
total 2,660 per candidate. December has 28 unscored pairs from missing actuals,
with identical coverage across candidates. Selection minimizes pooled MAE, with
RMSE only as tie-break. The winner does **not** win development RMSE or November
MAE. Weekly features remain optional; the selected model uses the original SCADA
feature set. Full grid and reproduction: [ML training](ml-training.md).

Selected parameters: `scada`, MAE objective, 500 trees, depth 4, learning rate 0.04,
L2 10, seed 42, daily origins, two CPU threads. The plan and winner were saved
before January evaluation, with no later parameter changes. January had already
been inspected for the original baseline: this is a reused comparison period,
not an untouched test. No random split, future weather measurements or February
targets were used.

## January comparison

Cutoff: January 1, 2026, 00:00 UTC. Training origins: April 1, 2023 through December
29, 2025; 91,720 fitting pairs. Evaluation: January 1–28 daily at 00:00 UTC, leads
1..48; 2,688 scored pairs, zero missing, 672 per row below. The model stays fixed;
earlier January observations become features only after their availability time.
Overlapping issue/target pairs are correlated, not independent trials.

| Turbine | Lead hours | Previous MAE | Selected MAE | Previous RMSE | Selected RMSE |
| --- | --- | --- | --- | --- | --- |
| 1 | 1–24 | 0.27689 | **0.26407** | 0.32577 | **0.32310** |
| 1 | 25–48 | 0.32187 | **0.30253** | 0.36032 | **0.35196** |
| 2 | 1–24 | 0.27730 | **0.26014** | 0.32096 | **0.31853** |
| 2 | 25–48 | 0.31730 | **0.29350** | 0.35390 | **0.34552** |

| Model | Pooled MAE | Pooled RMSE |
| --- | --- | --- |
| Persistence | 0.34360 | 0.45567 |
| Previous CatBoost | 0.29834 | 0.34067 |
| Selected CatBoost | **0.28006** | **0.33508** |

MAE is normalized-power error, not an accuracy percentage. These errors remain
large on [0,1]. Two development folds and a reused January comparison do not
establish general superiority across seasons or future years.

## Local models and forecast

- Evaluation model: `model-1ce9040924c14cd583a3924c7860c2ee`, cutoff January 1.
  The January metrics above belong to this model.
- Refit: `model-278bd6130ed3466ca981f75368f0df8e`, cutoff **January 31, 2026,
  00:00 UTC**, 94,600 training pairs, origins through January 28, same parameters.
  **These refitted weights have no measured February score.**
- Dataset: `dataset-c7dce26f9fb940fdb33a1a53aad3a5b2`, 48,452 complete hours.
- Previous model retained: `model-27c6f4072b7a441d80ede55745eb4f60`.

IDs are local; teammates obtain new IDs by reproducing the commands. Models are
registered in the API database with native weights under `artifacts/models/<id>/`.
The refit passed the agent flow: run `run-d27adad83b5f4c1f8616fac8f60154fe`, 96
points. This smoke check uses demo weather, which SCADA inference ignores with
an explicit warning. It checks integration, not accuracy.

For `POST /api/v1/forecasts` at `http://127.0.0.1:8000/docs`:

```json
{
  "turbine_ids": ["turbine-1", "turbine-2"],
  "issued_at": "2026-01-31T00:00:00Z",
  "horizon_hours": 48,
  "weather_source": "demo",
  "model_id": "model-278bd6130ed3466ca981f75368f0df8e"
}
```

The refit rejects issues before its cutoff. Earlier January scores cannot be
assigned to these later-trained weights.

## Evidence and limitations

The committed [metric summary](model-selection-results.json) includes every
candidate/fold score, parameters, source hashes and time semantics. Detailed local files:

- `artifacts/tuning/selection-c007751c7c6b49008fc5751f4b626653/selection.json`
- `artifacts/tuning/selection-c007751c7c6b49008fc5751f4b626653/january/experiment-4d49a9c6bf6146b188f08f46dd4194ba/report.json`
- The sibling `predictions.csv` contains every January prediction.
- `artifacts/refits/refit-99bb4b5a840c408f94ed13f5d713d563/report.json`
- The refit directory also contains smoke-check `forecast.json` and `forecast.csv`.

The search resumed after a merge temporarily interrupted one subprocess. The
fixed plan, completed reports and failed log were preserved. Older individual fold
reports say no tuning on validation because each fit was fixed; these folds are
explicitly **development data used for selection** in this aggregate report.

Timing is confirmed as fixed UTC+06:00 / interval start. Reporting delay (assumed
10 minutes) and physical normalization remain unconfirmed, so `is_demo=true`
marks provisional results. Main's candidate weather archives need publication
verification. February actuals are absent. Verified weather integration and the
February replay required by `docs/task.pdf` remain open. No new raw readings,
native weights or individual predictions are committed by this PR.
