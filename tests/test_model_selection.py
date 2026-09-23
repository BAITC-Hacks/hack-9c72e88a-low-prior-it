from copy import deepcopy
from math import sqrt

import pytest
from wind_backend.model_selection import aggregate_metrics, refit_request, select_winner


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


def test_refit_keeps_selected_parameters_and_rejects_historical_cutoff():
    candidate = dict(
        name="winner",
        feature_set="scada",
        loss_function="MAE",
        depth=4,
        iterations=500,
        learning_rate=0.04,
        l2_leaf_reg=10,
        origin_step_hours=24,
    )
    selection = dict(
        selected=candidate,
        plan=dict(
            january_used_for_selection=False,
            first_origin="2023-04-01T00:00:00Z",
            random_seed=42,
            folds=[dict(end="2025-12-14T00:00:00Z")],
        ),
        results=[
            dict(
                candidate=candidate,
                folds=[
                    dict(
                        name="december",
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
        ],
    )
    trained = refit_request(selection, "dataset-fixture", "2026-01-31T00:00:00Z")
    assert trained.loss_function == "MAE" and trained.depth == 4 and trained.iterations == 500
    assert trained.last_origin.isoformat() == "2026-01-28T00:00:00+00:00"
    with pytest.raises(ValueError, match="development targets"):
        refit_request(selection, "dataset-fixture", "2025-12-16T00:00:00Z")
    selection["selected"] = candidate | {"depth": 8}
    with pytest.raises(ValueError, match="frozen"):
        refit_request(selection, "dataset-fixture", "2026-01-31T00:00:00Z")


def test_selection_rejects_different_pairs_despite_matching_cell_counts():
    candidate = dict(
        candidate=dict(name="one"),
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
                        ],
                        scored_pairs_sha256="a" * 64,
                    )
                },
            )
        ],
    )
    other = deepcopy(candidate)
    other["candidate"]["name"] = "two"
    other["folds"][0]["comparison"]["catboost"]["scored_pairs_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="identical issue/target pairs"):
        select_winner([candidate, other])
