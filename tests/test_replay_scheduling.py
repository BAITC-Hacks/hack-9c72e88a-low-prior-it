import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from wind_backend.service import WindService
from wind_backend.storage import Repository
from wind_contracts.models import BacktestRequest, Turbine


def test_archive_replay_yields_for_status_polling_between_days(tmp_path, monkeypatch):
    service = WindService(
        Repository(tmp_path / "replay.sqlite3"),
        [Turbine(id="turbine-1", name="Fixture")],
    )
    request = BacktestRequest(
        turbine_ids=["turbine-1"],
        issued_at=datetime(2026, 1, 31, 12, tzinfo=UTC),
        last_issued_at=datetime(2026, 2, 28, 12, tzinfo=UTC),
        horizon_hours=48,
        weather_source="archive",
        model_id="demo-power-curve",
        evaluation_start=datetime(2026, 2, 1, tzinfo=UTC),
        evaluation_end=datetime(2026, 3, 1, tzinfo=UTC),
    )
    run = service.create_backtest(request)
    completed = []

    def create_forecast(payload):
        return SimpleNamespace(id=f"run-fixture-{len(completed) + 1}")

    async def execute_forecast(identifier, *, include_analysis):
        # Deliberately no await: an offline archive + local model need not yield.
        assert include_analysis is False
        completed.append(identifier)
        return SimpleNamespace(status="succeeded", result=SimpleNamespace(points=[]))

    monkeypatch.setattr(service, "create_forecast", create_forecast)
    monkeypatch.setattr(service, "execute_forecast", execute_forecast)
    observed = []

    async def poll_status():
        while True:
            status = service.required("backtest", run.id)
            observed.append((status["status"], len(status["forecast_ids"])))
            if status["status"] != "running":
                break
            await asyncio.sleep(0)

    async def replay_and_poll():
        await asyncio.gather(service.execute_backtest(run.id), poll_status())

    asyncio.run(replay_and_poll())
    assert len(completed) == 29
    assert any(status == "running" and 0 < count < 29 for status, count in observed)
    assert observed[-1] == ("succeeded", 29)
