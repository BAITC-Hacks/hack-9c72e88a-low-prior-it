# CatBoost experiment with corrected source timing (provisional)

Experiment: `experiment-cf8d190e16ad47d9a67e3a4bd627dc27`.
Model: `model-27c6f4072b7a441d80ede55745eb4f60` (`catboost-scada-v1`).
Dataset: `dataset-11d73cf8339541d7aaa58f626f0a5dda`.

The original organizer files were used. The user confirmed fixed **UTC+06:00** and
**interval-start** source timestamps. Preparation converts to UTC and adds 10 minutes
before hourly aggregation. Latency and power normalization remain unconfirmed:
the assumed reporting delay is 10 minutes after interval end and source power
values are used unchanged in [0,1]. This is not a competition score. Preparation
revision `utc6-start-provisional-v2` records these details as described in
[ML training](ml-training.md), with `provisional=true` and model `is_demo=true`.
There are no synthetic SCADA rows or synthetic weather features in this experiment.

Two CPU CatBoost regressors were trained, one per turbine. Parameters: 300 trees,
depth 6, learning rate 0.05, seed 42, RMSE objective, two threads. Features contain
only origin-available SCADA summaries and target calendar/lead information. No
archived weather was supplied, and no future observed weather was substituted.

48,452 complete hourly observations were prepared. No source rows were quarantined.
Training uses daily origins
April 1, 2023 through December 29, 2025 at 00:00 UTC, with leads 1..48 and an
availability cutoff of January 1, 2026 at 00:00 UTC. There were 44,742 training
issue/target pairs for turbine 1 and 46,978 for turbine 2. Respectively 3,450 and
1,214 missing/late target pairs were omitted and counted.

Validation uses daily origins January 1–28, 2026 at 00:00 UTC, each forecasting the
next 48 hours. Models are fixed during validation. Earlier validation observations
can become features after their assumed availability time; future ones cannot.
Overlapping issue/target pairs remain separate samples. Each row below has 672
scored pairs; there are 2,688 total and zero missing validation actuals.

| Turbine | Lead hours | CatBoost MAE | Persistence MAE | CatBoost RMSE | Persistence RMSE |
| --- | --- | --- | --- | --- | --- |
| 1 | 1–24 | 0.27689 | 0.32306 | 0.32577 | 0.44327 |
| 1 | 25–48 | 0.32187 | 0.37304 | 0.36032 | 0.47607 |
| 2 | 1–24 | 0.27730 | 0.32053 | 0.32096 | 0.43860 |
| 2 | 25–48 | 0.31730 | 0.35777 | 0.35390 | 0.46374 |

Sample-weighted MAE: CatBoost 0.29834 versus persistence 0.34360, approximately
13.2% lower. These errors are still large on a [0,1] scale. This single chronological
holdout does not establish general superiority or an official February result.
No hyperparameter selection was performed against these scores.

Full parameters, feature importance, source hashes and metrics:
`artifacts/experiments/experiment-cf8d190e16ad47d9a67e3a4bd627dc27/report.json`.
Per-origin predictions are in the sibling `predictions.csv`.
Native models and checksums are under `artifacts/models/model-27c6f4072b7a441d80ede55745eb4f60/`.

The earlier experiment `experiment-b8339a368334483eb7f9226d1dbd124f` and model
`model-02a5530154014db586f1320405a54ae2` used the superseded `Asia/Almaty` / interval-end
interpretation. Their artifacts remain available for audit; use the new model for
subsequent forecasts. Hyperparameters and UTC validation origins were unchanged.

Next priorities: confirm latency and normalization, obtain verified archived forecasts,
then compare the weather-plus-SCADA model on a fixed pre-February validation plan.
February actuals are absent from the supplied CSVs; February accuracy cannot yet
be measured. Reproduction commands are in [ML training](ml-training.md).
