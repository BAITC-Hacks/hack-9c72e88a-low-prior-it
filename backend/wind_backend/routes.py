from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import Response

from wind_contracts import (
    BacktestRequest, BacktestRun, DatasetImport, DatasetInfo, Event, ForecastRequest,
    ForecastRun, ModelInfo, Observation, TrainRequest, Turbine, UTC, WeatherFetch, WeatherSnapshot,
)

router = APIRouter(prefix="/api/v1")


def service(request: Request):
    return request.app.state.service


@router.get("/turbines", response_model=list[Turbine])
def turbines(request: Request):
    return service(request).turbines


@router.get("/datasets", response_model=list[DatasetInfo])
def datasets(request: Request):
    return [d["info"] for d in service(request).storage.list("dataset")]


@router.post("/datasets", response_model=DatasetInfo, status_code=201)
def import_dataset(body: DatasetImport, request: Request):
    return service(request).import_dataset(body)


@router.get("/datasets/{identity}/observations", response_model=list[Observation])
def observations(identity: str, request: Request, start: UTC, end: UTC):
    rows = service(request).storage.get("dataset", identity)["observations"]
    parsed = [Observation.model_validate(r) for r in rows]
    return [r for r in parsed if start <= r.valid_time <= end]


@router.get("/models", response_model=list[ModelInfo])
def models(request: Request):
    return service(request).models()


@router.post("/models/train", response_model=ModelInfo, status_code=201)
def train(body: TrainRequest, request: Request):
    return service(request).train(body)


@router.get("/weather/snapshots", response_model=list[WeatherSnapshot])
def snapshots(request: Request, turbine_id: str | None = None):
    rows = service(request).storage.list("weather")
    return [row for row in rows if turbine_id is None or row["turbine_id"] == turbine_id]


@router.post("/weather/snapshots", response_model=WeatherSnapshot, status_code=201)
def import_snapshot(body: WeatherSnapshot, request: Request):
    return service(request).import_weather(body)


@router.post("/weather/fetch", response_model=WeatherSnapshot, status_code=201)
def fetch(body: WeatherFetch, request: Request):
    return service(request).fetch_weather(body)


@router.get("/forecasts", response_model=list[ForecastRun])
def forecasts(request: Request, limit: int = Query(20, ge=1, le=200)):
    return service(request).storage.list("forecast")[:limit]


@router.post("/forecasts", response_model=ForecastRun, status_code=202)
def forecast(body: ForecastRequest, request: Request, tasks: BackgroundTasks):
    svc = service(request)
    run, prepared = svc.queue_forecast(body)
    if prepared:
        tasks.add_task(svc.execute_forecast, run.id, prepared)
    return run


@router.get("/forecasts/{identity}", response_model=ForecastRun)
def get_forecast(identity: str, request: Request):
    return service(request).storage.get("forecast", identity)


@router.get("/forecasts/{identity}/events", response_model=list[Event])
def events(identity: str, request: Request):
    return service(request).storage.get("forecast", identity)["events"]


@router.post("/forecasts/{identity}/refresh", response_model=ForecastRun, status_code=202)
def refresh(identity: str, request: Request, tasks: BackgroundTasks):
    previous = service(request).storage.get("forecast", identity)
    return forecast(ForecastRequest.model_validate(previous["request"]), request, tasks)


def export_response(request, kind, identity):
    text = service(request).export(kind, identity)
    return Response(text, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'})


@router.get("/forecasts/{identity}/export", response_class=Response,
            responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}})
def forecast_export(identity: str, request: Request):
    return export_response(request, "forecast", identity)


@router.get("/backtests", response_model=list[BacktestRun])
def backtests(request: Request):
    return service(request).storage.list("backtest")


@router.post("/backtests", response_model=BacktestRun, status_code=202)
def replay(body: BacktestRequest, request: Request, tasks: BackgroundTasks):
    svc = service(request)
    run = svc.queue_backtest(body)
    tasks.add_task(svc.execute_backtest, run.id)
    return run


@router.get("/backtests/{identity}", response_model=BacktestRun)
def get_backtest(identity: str, request: Request):
    return service(request).storage.get("backtest", identity)


@router.get("/backtests/{identity}/export", response_class=Response,
            responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}})
def backtest_export(identity: str, request: Request):
    return export_response(request, "backtest", identity)
