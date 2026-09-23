import pytest
from pydantic import ValidationError
from wind_contracts.models import EnergyAsset


def test_assets_expose_configured_wind_and_forecast_mapping(client, forecast_request):
    response = client.get("/api/v1/assets")
    assert response.status_code == 200
    assets = response.json()
    turbines = client.get("/api/v1/turbines").json()
    assert {asset["id"] for asset in assets} == {turbine["id"] for turbine in turbines}
    assert len(assets) == 2
    assert {asset["energy_type"] for asset in assets} == {"wind"}
    assert {asset["country_code"] for asset in assets} == {"KZ"}
    assert {asset["country_name"] for asset in assets} == {"Kazakhstan"}
    assert {asset["site_id"] for asset in assets} == {"kazakhstan-wind-site"}
    assert {asset["site_name"] for asset in assets} == {"Kazakhstan wind site"}
    configured = {turbine["id"]: turbine for turbine in turbines}
    for asset in assets:
        assert asset["forecast_supported"] is True
        assert asset["forecast_turbine_id"] == asset["id"]
        for field in ("latitude", "longitude", "rated_power_kw"):
            assert asset[field] == configured[asset["id"]][field]

    # Explore selections must work with the existing forecast contract unchanged.
    request = forecast_request | {
        "turbine_ids": [asset["forecast_turbine_id"] for asset in assets],
    }
    created = client.post("/api/v1/forecasts", json=request)
    assert created.status_code == 202
    run = client.get(f"/api/v1/forecasts/{created.json()['id']}").json()
    assert run["status"] == "succeeded"
    assert len(run["result"]["points"]) == 96


def test_asset_location_metadata_is_explicit_and_optional(client, monkeypatch):
    turbine = client.app.state.service.turbines["turbine-1"]
    for field in ("country_code", "country_name", "site_id", "site_name"):
        monkeypatch.setattr(turbine, field, None)
    asset = next(
        asset for asset in client.get("/api/v1/assets").json() if asset["id"] == turbine.id
    )
    assert asset["latitude"] == turbine.latitude
    assert asset["longitude"] == turbine.longitude
    assert asset["country_code"] is None
    assert asset["country_name"] is None
    assert asset["site_id"] is None
    assert asset["site_name"] is None


@pytest.mark.parametrize("energy_type", ["wind", "hydro", "solar", "other"])
def test_registry_accepts_future_asset_types_without_claiming_forecasts(energy_type):
    asset = EnergyAsset(id="future-asset", name="Future asset", energy_type=energy_type)
    assert asset.forecast_supported is False
    assert asset.forecast_turbine_id is None


@pytest.mark.parametrize("energy_type", ["hydro", "solar", "other"])
def test_current_forecasting_capability_is_wind_only(energy_type):
    with pytest.raises(ValidationError, match="mapped wind turbine"):
        EnergyAsset(
            id="future-asset",
            name="Future asset",
            energy_type=energy_type,
            forecast_supported=True,
            forecast_turbine_id="turbine-1",
        )
