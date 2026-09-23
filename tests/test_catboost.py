import math
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from wind_backend.catboost_model import CatBoostPower, select_snapshot
from wind_backend.features import (
    EXTENDED_FEATURE_NAMES,
    FEATURE_NAMES,
    SCADA_FEATURE_NAMES,
    ObservationHistory,
    build_features,
    build_scada_features,
)
from wind_backend.main import create_app
from wind_backend.ml import BinnedPowerCurve, PersistencePredictor
from wind_contracts.models import (
    ForecastRequest,
    Observation,
    TrainRequest,
    Turbine,
    WeatherPoint,
    WeatherSnapshot,
)

BASE = datetime(2026, 1, 10, tzinfo=UTC)
TURBINE = Turbine(id="turbine-1", name="One")


def observations():
    return [
        Observation(
            turbine_id=turbine,
            valid_time=BASE + timedelta(hours=i),
            available_at=BASE + timedelta(hours=i, minutes=10),
            wind_speed_ms=8 + math.sin(i / 4),
            temperature_c=5,
            power_normalized=0.4 + 0.3 * math.sin(i / 7 + n),
        )
        for n, turbine in enumerate(["turbine-1", "turbine-2"])
        for i in range(-30, 145)
    ]


def request(**updates):
    return TrainRequest.model_validate(
        dict(
            dataset_id="dataset-test",
            algorithm="catboost",
            trained_through=BASE + timedelta(hours=73),
            first_origin=BASE,
            last_origin=BASE + timedelta(days=1),
            iterations=10,
            depth=2,
        )
        | updates
    )


def weather(origin, hours=48):
    return [
        WeatherPoint(
            valid_time=origin + timedelta(hours=i),
            wind_speed_ms=8,
            wind_direction_deg=90,
            temperature_c=5,
        )
        for i in range(1, hours + 1)
    ]


def test_feature_values_and_missing_windows():
    history = ObservationHistory(observations())
    targets = [BASE + timedelta(hours=1), BASE + timedelta(hours=48)]
    features = build_scada_features(history, TURBINE.id, targets, BASE)
    assert len(features[0]) == len(SCADA_FEATURE_NAMES)
    values = dict(zip(SCADA_FEATURE_NAMES, features[0], strict=True))
    assert values["observation_age_hours"] == 1  # zero-hour reading is not reported yet
    assert values["power_count_3h"] == 2
    assert values["lead_hours"] == 1
    assert features[0][5:] == features[1][5:]  # every lead has the SAME as-of SCADA
    weather_features = build_features(history, TURBINE.id, weather(BASE), BASE)
    assert len(weather_features[0]) == len(FEATURE_NAMES)
    assert weather_features[0][:4] == pytest.approx([8, 1, 0, 5])
    stale = ObservationHistory(observations()[:1])
    stale_values = dict(
        zip(
            SCADA_FEATURE_NAMES,
            build_scada_features(stale, TURBINE.id, targets, BASE)[0],
            strict=True,
        )
    )
    assert stale_values["power_count_24h"] == 0
    assert math.isnan(stale_values["power_mean_24h"])


def test_future_and_delayed_observations_do_not_change_features():
    rows = observations()
    expected = build_scada_features(
        ObservationHistory(rows), TURBINE.id, [BASE + timedelta(hours=1)], BASE
    )
    changed = [
        r.model_copy(update={"power_normalized": 1.0, "wind_speed_ms": 99.0})
        if r.available_at > BASE
        else r
        for r in rows
    ]
    assert (
        build_scada_features(
            ObservationHistory(changed), TURBINE.id, [BASE + timedelta(hours=1)], BASE
        )
        == expected
    )


def test_persistence_uses_latest_available_per_origin_not_training_cutoff():
    rows = observations()
    model = PersistencePredictor.fit("model-p", "dataset-x", rows, BASE)
    origin = BASE + timedelta(days=2)
    result = model.predict(TURBINE, weather(origin), origin)
    expected = next(
        r.power_normalized
        for r in rows
        if r.turbine_id == TURBINE.id and r.valid_time == origin - timedelta(hours=1)
    )
    assert {p.power_normalized for p in result} == {expected}
    with pytest.raises(ValueError, match="cutoff"):
        model.predict(TURBINE, weather(BASE - timedelta(hours=1)), BASE - timedelta(hours=1))


@pytest.mark.parametrize("feature_set", ["scada", "scada-extended"])
def test_catboost_training_roundtrip_and_checksum(tmp_path, feature_set):
    rows = observations()
    model = CatBoostPower.fit("model-c", rows, request(feature_set=feature_set))
    assert model.info.training_rows == 192
    assert len(model.models) == 2
    origin = BASE + timedelta(hours=74)
    result = model.predict(TURBINE, weather(origin), origin)
    assert len(result) == 48 and all(0 <= p.power_normalized <= 1 for p in result)
    artifact = model.save(tmp_path)
    loaded = CatBoostPower.load(artifact, tmp_path, rows)
    assert loaded.predict(TURBINE, weather(origin), origin) == result
    with pytest.raises(ValueError, match="history checksum"):
        CatBoostPower.load(artifact, tmp_path, rows[:-1])
    path = tmp_path / model.info.id / "turbine-1.cbm"
    path.write_bytes(path.read_bytes() + b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        CatBoostPower.load(artifact, tmp_path, rows)


@pytest.mark.parametrize("feature_set", ["scada", "scada-extended"])
def test_future_training_labels_cannot_change_fit(feature_set):
    rows = observations()
    first = CatBoostPower.fit("model-a", rows, request(feature_set=feature_set))
    changed = [
        r.model_copy(update={"power_normalized": 1.0})
        if r.available_at > request().trained_through
        else r
        for r in rows
    ]
    second = CatBoostPower.fit("model-b", changed, request(feature_set=feature_set))
    # At the cutoff, changed rows are still unavailable as SCADA inputs, too.
    origin = request().trained_through
    assert first.predict(TURBINE, weather(origin), origin) == second.predict(
        TURBINE, weather(origin), origin
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"first_origin": None},
        {"last_origin": BASE + timedelta(days=4)},
        {"last_origin": BASE + timedelta(hours=1)},
        {"iterations": 0},
    ],
)
def test_training_contract_rejects_invalid_windows(changes):
    with pytest.raises(ValueError):
        request(**changes)


def test_weather_training_requires_archives_not_observed_future_weather():
    with pytest.raises(ValueError, match="eligible complete weather"):
        CatBoostPower.fit("model-w", observations(), request(feature_set="weather-scada"))
    with pytest.raises(ValueError, match="explicitly demo"):
        CatBoostPower.fit(
            "model-w", observations(), request(feature_set="weather-scada", weather_source="demo")
        )


def test_archive_selection_rejects_late_publication_and_records_lineage():
    snapshots = [
        WeatherSnapshot(
            id=f"archive-{i}",
            turbine_id=t,
            source="external-archive",
            weather_model="fixture-only",
            run_init=BASE - timedelta(hours=6),
            retrieved_at=BASE + timedelta(days=200),
            available_at=BASE,
            verification="verified",
            availability_evidence="unit-test fixture",
            wind_height_m=100,
            points=weather(BASE, 72),
        )
        for i, t in enumerate(["turbine-1", "turbine-2"])
    ]
    query = ForecastRequest(turbine_ids=[TURBINE.id], issued_at=BASE, weather_source="archive")
    late = snapshots[0].model_copy(update={"available_at": BASE + timedelta(seconds=1)})
    with pytest.raises(ValueError, match="eligible"):
        select_snapshot([late], TURBINE, query)
    model = CatBoostPower.fit(
        "model-w", observations(), request(feature_set="weather-scada"), snapshots
    )
    assert model.report["turbines"][TURBINE.id]["weather_lineage"][0]["snapshot_id"] == "archive-0"
    assert model.feature_set == "weather-scada"


@pytest.mark.parametrize("feature_set", ["scada", "scada-extended"])
def test_api_catboost_and_persistence_survive_restart(client, settings, feature_set):
    rows = [r.model_dump(mode="json") for r in observations()]
    dataset_id = client.post(
        "/api/v1/datasets", json={"name": "fixture", "is_demo": True, "observations": rows}
    ).json()["id"]
    trained = client.post(
        "/api/v1/models/train",
        json=request(dataset_id=dataset_id, feature_set=feature_set).model_dump(mode="json"),
    )
    assert trained.status_code == 201, trained.text
    info = trained.json()
    assert info["algorithm"] == f"catboost-{feature_set}-v1" and info["is_demo"]
    persistence = client.post(
        "/api/v1/models/train",
        json={
            "dataset_id": dataset_id,
            "algorithm": "persistence",
            "trained_through": request().trained_through.isoformat(),
        },
    )
    assert persistence.status_code == 201
    with TestClient(create_app(settings)) as restarted:
        for model in [info, persistence.json()]:
            created = restarted.post(
                "/api/v1/forecasts",
                json={
                    "turbine_ids": [TURBINE.id],
                    "issued_at": (BASE + timedelta(hours=74)).isoformat(),
                    "model_id": model["id"],
                },
            ).json()
            result = restarted.get(f"/api/v1/forecasts/{created['id']}").json()
            assert result["status"] == "succeeded", result
            assert len(result["result"]["points"]) == 48


def test_binned_direct_prediction_cannot_bypass_cutoff():
    model = BinnedPowerCurve.fit("model-b", "dataset-x", observations(), BASE + timedelta(hours=1))
    with pytest.raises(ValueError, match="cutoff"):
        model.predict(TURBINE, weather(BASE), BASE)


def test_extended_features_respect_clock_gaps_and_delayed_history():
    rows = [r for r in observations() if r.valid_time != BASE - timedelta(hours=2)]
    # An old event can also arrive after the origin; neither case may become a lag.
    rows = [
        r.model_copy(update={"available_at": BASE + timedelta(hours=1)})
        if r.valid_time == BASE - timedelta(hours=3)
        else r
        for r in rows
    ]

    def values(source):
        vector = build_scada_features(
            ObservationHistory(source),
            TURBINE.id,
            [BASE + timedelta(hours=48)],
            BASE,
            extended=True,
        )[0]
        return dict(zip(EXTENDED_FEATURE_NAMES, vector, strict=True))

    features = values(rows)
    assert features["power_lag_1h"] == features["last_power"]
    for lag in (2, 3, 168):
        assert math.isnan(features[f"power_lag_{lag}h"])
    assert features["power_count_48h"] == 28
    changed = [
        r.model_copy(update={"power_normalized": 1.0, "wind_speed_ms": 99.0})
        if r.available_at > BASE
        else r
        for r in rows
    ]
    for key, value in values(changed).items():
        assert math.isnan(value) if math.isnan(features[key]) else value == features[key]


def test_subdaily_origins_and_mae_training():
    model = CatBoostPower.fit(
        "model-halfday",
        observations(),
        request(
            origin_step_hours=12, loss_function="MAE", l2_leaf_reg=10, feature_set="scada-extended"
        ),
    )
    assert model.info.training_rows == 288  # three origins x two turbines x 48 leads
    assert model.report["parameters"]["loss_function"] == "MAE"
    with pytest.raises(ValueError):
        request(origin_step_hours=12, last_origin=BASE + timedelta(hours=18))
