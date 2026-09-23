from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from wind_agent.orchestrator import ForecastAgent
from wind_agent.weather import ArchiveWeatherProvider, DemoWeatherProvider
from wind_contracts.models import (
    AgentEvent,
    BacktestRequest,
    BacktestRun,
    DatasetInfo,
    DatasetUpload,
    ForecastRequest,
    ForecastRun,
    ModelInfo,
    TrainRequest,
    Turbine,
    WeatherSnapshot,
)

from wind_backend.evaluation import evaluate
from wind_backend.ml import BinnedPowerCurve, DemoPowerCurve, PersistencePredictor
from wind_backend.storage import Repository


class DomainError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


class WindService:
    def __init__(
        self,
        repository: Repository,
        turbines: list[Turbine],
        models_path: Path = Path("artifacts/models"),
    ):
        self.repository = repository
        self.turbines = {t.id: t for t in turbines}
        self.models_path = models_path

    def required(self, kind, identifier):
        value = self.repository.get(kind, identifier)
        if value is None:
            raise DomainError(404, "not_found", f"Unknown {kind}: {identifier}")
        return value

    def turbine(self, identifier):
        if identifier not in self.turbines:
            raise DomainError(404, "not_found", f"Unknown turbine: {identifier}")
        return self.turbines[identifier]

    def predictor(self, identifier):
        if identifier == "demo-power-curve":
            return DemoPowerCurve()
        artifact = self.required("model", identifier)
        info = ModelInfo.model_validate(artifact["info"])
        if info.algorithm == "binned-power-curve-v1":
            return BinnedPowerCurve(info, artifact["curves"])
        dataset = DatasetUpload.model_validate(self.required("dataset", info.dataset_id)["data"])
        if info.algorithm == "persistence-v1":
            return PersistencePredictor(info, dataset.observations)
        if info.algorithm == "weather-ridge-v1":
            from wind_backend.ridge_model import WeatherRidge

            return WeatherRidge(info, artifact["parameters"], dataset.observations)
        if info.algorithm in {
            "catboost-scada-v1",
            "catboost-scada-extended-v1",
            "catboost-weather-scada-v1",
        }:
            from wind_backend.catboost_model import CatBoostPower

            return CatBoostPower.load(artifact, self.models_path, dataset.observations)
        raise ValueError(f"Unsupported model algorithm: {info.algorithm}")

    def models(self):
        return [DemoPowerCurve.info] + [
            ModelInfo.model_validate(value["info"]) for value in self.repository.list("model")
        ]

    def upload_dataset(self, payload: DatasetUpload):
        for identifier in {row.turbine_id for row in payload.observations}:
            self.turbine(identifier)
        identifier = f"dataset-{uuid4().hex}"
        times = [row.valid_time for row in payload.observations]
        info = DatasetInfo(
            id=identifier,
            name=payload.name,
            is_demo=payload.is_demo,
            provenance=payload.provenance,
            rows=len(times),
            first_time=min(times),
            last_time=max(times),
        )
        self.repository.put(
            "dataset",
            identifier,
            {"info": info.model_dump(mode="json"), "data": payload.model_dump(mode="json")},
        )
        return info

    def train(self, payload: TrainRequest):
        dataset = DatasetUpload.model_validate(self.required("dataset", payload.dataset_id)["data"])
        identifier = f"model-{uuid4().hex}"
        if payload.algorithm == "catboost":
            from wind_backend.catboost_model import CatBoostPower

            model = CatBoostPower.fit(
                identifier, dataset.observations, payload, self.snapshots(), is_demo=dataset.is_demo
            )
            artifact = model.save(self.models_path)
        elif payload.algorithm == "weather-ridge":
            from wind_backend.ridge_model import WeatherRidge

            snapshots = (
                [
                    WeatherSnapshot.model_validate(self.required("weather", key))
                    for key in payload.weather_snapshot_ids
                ]
                if payload.weather_snapshot_ids
                else self.snapshots()
            )
            model = WeatherRidge.fit(
                identifier, dataset.observations, payload, snapshots, dataset.is_demo
            )
            artifact = {"info": model.info.model_dump(mode="json"), "parameters": model.parameters}
        else:
            model_class = (
                PersistencePredictor if payload.algorithm == "persistence" else BinnedPowerCurve
            )
            model = model_class.fit(
                identifier,
                payload.dataset_id,
                dataset.observations,
                payload.trained_through,
                is_demo=dataset.is_demo,
            )
            artifact = {"info": model.info.model_dump(mode="json")}
            if payload.algorithm == "binned-power-curve":
                artifact["curves"] = model.curves
        self.repository.put(
            "model",
            model.info.id,
            artifact,
        )
        return model.info

    def snapshots(self):
        return [WeatherSnapshot.model_validate(value) for value in self.repository.list("weather")]

    def store_snapshot(self, snapshot: WeatherSnapshot):
        self.turbine(snapshot.turbine_id)
        if self.repository.get("weather", snapshot.id) is not None:
            raise DomainError(409, "immutable_snapshot", "Use a new ID for each snapshot revision")
        self.repository.put("weather", snapshot.id, snapshot.model_dump(mode="json"))
        return snapshot

    def agent(self, request: ForecastRequest):
        provider = (
            DemoWeatherProvider()
            if request.weather_source == "demo"
            else ArchiveWeatherProvider(self.snapshots)
        )
        return ForecastAgent(provider, self.predictor(request.model_id))

    def validate_request(self, request: ForecastRequest):
        for identifier in request.turbine_ids:
            self.turbine(identifier)
        model = self.predictor(request.model_id)
        if model.info.trained_through and model.info.trained_through > request.issued_at:
            raise ValueError("Model training cutoff is later than forecast issue time")
        if model.info.id != "demo-power-curve" and not set(request.turbine_ids).issubset(
            model.info.turbine_ids
        ):
            raise ValueError("Model is missing training data for a requested turbine")

    def create_forecast(self, request: ForecastRequest):
        self.validate_request(request)
        run = ForecastRun(
            id=f"run-{uuid4().hex}", created_at=datetime.now(UTC), status="queued", request=request
        )
        self.save_forecast(run)
        return run

    def save_forecast(self, run):
        self.repository.put("forecast", run.id, run.model_dump(mode="json"))

    async def execute_forecast(self, identifier):
        run = ForecastRun.model_validate(self.required("forecast", identifier))
        run.status = "running"
        self.save_forecast(run)

        def emit(event):
            run.events.append(event)
            self.save_forecast(run)

        try:
            run.result = await self.agent(run.request).run(
                run.request, [self.turbine(t) for t in run.request.turbine_ids], emit
            )
            run.status = "succeeded"
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            emit(AgentEvent(at=datetime.now(UTC), stage="failed", message=run.error))
        self.save_forecast(run)
        return run

    async def refresh(self, identifier):
        previous = ForecastRun.model_validate(self.required("forecast", identifier))
        if previous.status != "succeeded" or previous.result is None:
            raise DomainError(409, "run_not_ready", "Only successful forecasts can be refreshed")
        _, token = await self.agent(previous.request).prepare(
            previous.request,
            [self.turbine(t) for t in previous.request.turbine_ids],
            lambda _: None,
        )
        if token == previous.result.input_fingerprint:
            return False, previous
        return True, self.create_forecast(previous.request)

    def create_backtest(self, request: BacktestRequest):
        self.validate_request(request)
        is_demo = request.weather_source == "demo" or self.predictor(request.model_id).info.is_demo
        if request.actuals_dataset_id:
            dataset = self.required("dataset", request.actuals_dataset_id)
            is_demo = is_demo or dataset["info"].get("is_demo", False)
        run = BacktestRun(
            id=f"backtest-{uuid4().hex}",
            created_at=datetime.now(UTC),
            is_demo=is_demo,
            status="queued",
            request=request,
        )
        self.save_backtest(run)
        return run

    def save_backtest(self, run):
        self.repository.put("backtest", run.id, run.model_dump(mode="json"))

    async def execute_backtest(self, identifier):
        run = BacktestRun.model_validate(self.required("backtest", identifier))
        run.status = "running"
        self.save_backtest(run)
        points = []
        try:
            issue = run.request.issued_at
            while issue <= run.request.last_issued_at:
                payload = run.request.model_dump(include=set(ForecastRequest.model_fields))
                payload["issued_at"] = issue
                child = self.create_forecast(ForecastRequest.model_validate(payload))
                run.forecast_ids.append(child.id)
                self.save_backtest(run)
                child = await self.execute_forecast(child.id)
                if child.status != "succeeded":
                    raise ValueError(f"{child.id}: {child.error}")
                points.extend(
                    point
                    for point in child.result.points
                    if run.request.evaluation_start <= point.valid_time < run.request.evaluation_end
                )
                issue += timedelta(days=1)
            actuals = []
            if run.request.actuals_dataset_id:
                dataset = self.required("dataset", run.request.actuals_dataset_id)
                actuals = DatasetUpload.model_validate(dataset["data"]).observations
            run.metrics, run.scored_points, run.unscored_points = evaluate(points, actuals)
            run.status = "succeeded"
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
        self.save_backtest(run)

    def recover_interrupted_jobs(self):
        # In-process tasks do not survive a restart. Expose this explicitly instead of leaving a spinner forever.
        for kind in ("forecast", "backtest"):
            for run in self.repository.list(kind):
                if run["status"] in ("queued", "running"):
                    run["status"] = "failed"
                    run["error"] = "API restarted before job completion; submit a new run"
                    self.repository.put(kind, run["id"], run)
