from copy import deepcopy
from math import sqrt

import pytest
from wind_backend.model_selection import aggregate_metrics, select_winner


def test_pooled_metrics_weight_by_samples_and_pool_squared_error():
    assert aggregate_metrics(
        [dict(samples=1, mae=0.1, rmse=0.2), dict(samples=3, mae=0.3, rmse=0.4)]
    ) == pytest.approx(dict(samples=4, mae=0.25, rmse=sqrt(0.13)))
    for bad in ([], [dict(samples=0, mae=0, rmse=0)], [dict(samples=1, mae=float("nan"), rmse=1)]):
        with pytest.raises(ValueError):
            aggregate_metrics(bad)


def test_selection_recomputes_scores_and_rejects_different_coverage():
    baseline = dict(
        candidate=dict(name="baseline"),
        folds=[
            dict(
                name="november",
                comparison={
                    "catboost": dict(
                        metrics=[
                            dict(
                                turbine_id="turbine-1",
                                horizon="1-24",
                                samples=48,
                                mae=0.2,
                                rmse=0.3,
                            )
                        ]
                    )
                },
            )
        ],
    )
    candidate = deepcopy(baseline)
    candidate["candidate"]["name"] = "candidate"
    metric = candidate["folds"][0]["comparison"]["catboost"]["metrics"][0]
    metric["mae"] = 0.3
    candidate["pooled"] = dict(mae=0.01, rmse=0.01)  # untrusted cached score
    assert select_winner([candidate, baseline]) is baseline
    metric["horizon"] = "25-48"
    with pytest.raises(ValueError, match="coverage"):
        select_winner([baseline, candidate])
