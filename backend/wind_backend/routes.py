import csv
import io
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response
from wind_agent.weather import download_single_run
from wind_contracts.evidence import EvidenceReport
from wind_contracts.models import (
    AgentEvent,
    AgentStatus,
    BacktestRequest,
    BacktestRun,
    DatasetInfo,
    DatasetUpload,
    EnergyAsset,
    ForecastRequest,
    ForecastRun,
    ModelInfo,
    Observation,
    RefreshResponse,
    Timestamp,
    TrainRequest,
    Turbine,
    WeatherFetchRequest,
    WeatherSnapshot,
)

from wind_backend.evidence import load_evidence
from wind_backend.service import DomainError, WindService

router = APIRouter(prefix="/api/v1")


def get_service(request: Request) -> WindService:
    return request.app.state.service


Service = Annotated[WindService, Depends(get_service)]


@router.get("/agent/status", response_model=AgentStatus, tags=["Agent"])
def agent_status(service: Service):
    return service.agent_status()


@router.get("/evidence", response_model=EvidenceReport, tags=["Model evidence"])
def evidence():
    return load_evidence()


@router.get("/evidence/export", response_model=EvidenceReport, tags=["Model evidence"])
def export_evidence(response: Response):
    response.headers["Content-Disposition"] = 'attachment; filename="wind-model-evidence.json"'
    return load_evidence()


@router.get("/assets", response_model=list[EnergyAsset], tags=["Energy assets"])
def assets(service: Service):
    return [
        EnergyAsset(
            id=turbine.id,
            name=turbine.name,
            energy_type="wind",
            country_code=turbine.country_code,
            country_name=turbine.country_name,
            site_id=turbine.site_id,
            site_name=turbine.site_name,
            latitude=turbine.latitude,
            longitude=turbine.longitude,
            rated_power_kw=turbine.rated_power_kw,
            forecast_supported=True,
            forecast_turbine_id=turbine.id,
        )
        for turbine in service.turbines.values()
    ]


@router.get("/turbines", response_model=list[Turbine], tags=["Turbines"])
def turbines(service: Service):
    return list(service.turbines.values())


@router.get("/datasets", response_model=list[DatasetInfo], tags=["Data and ML"])
def datasets(service: Service):
    return [value["info"] for value in service.repository.list("dataset")]


@router.post("/datasets", response_model=DatasetInfo, status_code=201, tags=["Data and ML"])
def upload_dataset(payload: DatasetUpload, service: Service):
    return service.upload_dataset(payload)


@router.get(
    "/datasets/{dataset_id}/observations", response_model=list[Observation], tags=["Data and ML"]
)
def observations(dataset_id: str, start: Timestamp, end: Timestamp, service: Service):
    if end < start:
        raise ValueError("Observation window end must be at or after start")
    dataset = DatasetUpload.model_validate(service.required("dataset", dataset_id)["data"])
    return sorted(
        [row for row in dataset.observations if start <= row.valid_time <= end],
        key=lambda row: (row.valid_time, row.turbine_id),
    )


@router.get("/models", response_model=list[ModelInfo], tags=["Data and ML"])
def models(service: Service):
    return service.models()


@router.post("/models/train", response_model=ModelInfo, status_code=201, tags=["Data and ML"])
def train_model(payload: TrainRequest, service: Service):
    return service.train(payload)


@router.get("/weather/snapshots", response_model=list[WeatherSnapshot], tags=["Weather"])
def snapshots(service: Service, turbine_id: str | None = None):
    return [s for s in service.snapshots() if turbine_id is None or s.turbine_id == turbine_id]


@router.post(
    "/weather/snapshots", response_model=WeatherSnapshot, status_code=201, tags=["Weather"]
)
def import_snapshot(payload: WeatherSnapshot, service: Service):
    return service.store_snapshot(payload)


@router.post("/weather/fetch", response_model=WeatherSnapshot, status_code=201, tags=["Weather"])
async def fetch_weather(payload: WeatherFetchRequest, service: Service):
    snapshot = await download_single_run(
        service.turbine(payload.turbine_id), payload.run_init, payload.weather_model
    )
    return service.store_snapshot(snapshot)


@router.get("/forecasts", response_model=list[ForecastRun], tags=["Forecasts"])
def forecasts(service: Service, limit: int = Query(default=20, ge=1, le=100)):
    return service.repository.list("forecast")[:limit]


@router.post("/forecasts", response_model=ForecastRun, status_code=202, tags=["Forecasts"])
def start_forecast(payload: ForecastRequest, tasks: BackgroundTasks, service: Service):
    run = service.create_forecast(payload)
    tasks.add_task(service.execute_forecast, run.id)
    return run


@router.get("/forecasts/{run_id}", response_model=ForecastRun, tags=["Forecasts"])
def forecast(run_id: str, service: Service):
    return service.required("forecast", run_id)


@router.get("/forecasts/{run_id}/events", response_model=list[AgentEvent], tags=["Forecasts"])
def forecast_events(run_id: str, service: Service):
    return service.required("forecast", run_id)["events"]


@router.post("/forecasts/{run_id}/refresh", response_model=RefreshResponse, tags=["Forecasts"])
async def refresh_forecast(run_id: str, tasks: BackgroundTasks, service: Service):
    changed, run = await service.refresh(run_id)
    if changed:
        tasks.add_task(service.execute_forecast, run.id)
    return RefreshResponse(changed=changed, run=run)


def forecast_csv(runs: list[ForecastRun], start=None, end=None):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "run_id",
            "issued_at",
            "turbine_id",
            "valid_time",
            "lead_hours",
            "power_normalized",
            "model_id",
            "weather_snapshot_id",
            "weather_run_init",
            "weather_available_at",
            "is_demo",
        ]
    )
    for run in runs:
        if run.result is None:
            continue
        provenance = {s.turbine_id: s for s in run.result.snapshots}
        for point in run.result.points:
            if start is not None and not start <= point.valid_time < end:
                continue
            source = provenance[point.turbine_id]
            writer.writerow(
                [
                    run.id,
                    run.request.issued_at.isoformat(),
                    point.turbine_id,
                    point.valid_time.isoformat(),
                    point.lead_hours,
                    point.power_normalized,
                    run.result.model_id,
                    source.id,
                    source.run_init.isoformat(),
                    source.available_at.isoformat(),
                    run.result.is_demo,
                ]
            )
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="forecast.csv"'},
    )


@router.get(
    "/forecasts/{run_id}/export",
    response_class=Response,
    tags=["Forecasts"],
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
def export_forecast(run_id: str, service: Service):
    run = ForecastRun.model_validate(service.required("forecast", run_id))
    if run.status != "succeeded":
        raise DomainError(409, "run_not_ready", "Forecast is not successful yet")
    return forecast_csv([run])


@router.get("/backtests", response_model=list[BacktestRun], tags=["Replay"])
def backtests(service: Service):
    return service.repository.list("backtest")


@router.post("/backtests", response_model=BacktestRun, status_code=202, tags=["Replay"])
def start_backtest(payload: BacktestRequest, tasks: BackgroundTasks, service: Service):
    run = service.create_backtest(payload)
    tasks.add_task(service.execute_backtest_background, run.id)
    return run


@router.get("/backtests/{run_id}", response_model=BacktestRun, tags=["Replay"])
def backtest(run_id: str, service: Service):
    return service.required("backtest", run_id)


@router.get(
    "/backtests/{run_id}/export",
    response_class=Response,
    tags=["Replay"],
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
def export_backtest(run_id: str, service: Service):
    run = BacktestRun.model_validate(service.required("backtest", run_id))
    if run.status != "succeeded":
        raise DomainError(409, "run_not_ready", "Backtest is not successful yet")
    children = [
        ForecastRun.model_validate(service.required("forecast", identifier))
        for identifier in run.forecast_ids
    ]
    return forecast_csv(children, run.request.evaluation_start, run.request.evaluation_end)
