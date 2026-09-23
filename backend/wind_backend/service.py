import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4

from wind_agent.interfaces import ForecastError
from wind_agent.orchestrator import ForecastAgent, fingerprint
from wind_agent.weather import ArchiveWeather, DemoWeather
from wind_contracts import (
    APIError, BacktestRun, DatasetInfo, ForecastRequest, ForecastRun, Observation, WeatherSnapshot,
)

from .evaluation import evaluate
from .ml import ModelPredictor, demo_model, train

logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc)


class Service:
    def __init__(self, storage, turbines, adapter):
        self.storage, self.turbines, self.adapter = storage, turbines, adapter
        self.lock = RLock()
        self.storage.recover()

    def assets(self, ids):
        configured = {t.id: t for t in self.turbines}
        if not set(ids) <= set(configured):
            raise ForecastError("unknown_turbine", "Unknown turbine ID", 404)
        return [configured[i] for i in sorted(ids)]

    def import_dataset(self, data):
        self.assets({r.turbine_id for r in data.observations})
        rows = sorted(data.observations, key=lambda r: (r.turbine_id, r.valid_time))
        digest = fingerprint([r.model_dump(mode="json") for r in rows])
        info = DatasetInfo(id=f"dataset-{uuid4().hex}", name=data.name, demo=data.demo, provenance=data.provenance,
            row_count=len(rows), start=min(r.valid_time for r in rows), end=max(r.valid_time for r in rows), fingerprint=digest)
        self.storage.insert("dataset", {"id": info.id, "info": info.model_dump(mode="json"),
                                        "observations": [r.model_dump(mode="json") for r in rows]})
        return info

    def import_weather(self, snapshot):
        self.assets([snapshot.turbine_id])
        self.storage.insert("weather", snapshot.model_dump(mode="json"))
        return snapshot

    def fetch_weather(self, request):
        turbine = self.assets([request.turbine_id])[0]
        return self.import_weather(self.adapter.fetch(request, turbine))

    def models(self):
        return [demo_model()["info"]] + [r["info"] for r in self.storage.list("model")]

    def train(self, request):
        dataset = self.storage.get("dataset", request.dataset_id)
        snapshots = [WeatherSnapshot.model_validate(self.storage.get("weather", i)) for i in request.weather_snapshot_ids]
        artifact = train(request, dataset, snapshots)
        self.storage.insert("model", artifact)
        return artifact["info"]

    def predictor(self, model_id):
        artifact = demo_model() if model_id == "demo-power-curve" else self.storage.get("model", model_id)
        info = artifact["info"]
        rows = []
        if info["algorithm"] in ("persistence", "weather-ridge"):
            rows = [Observation.model_validate(r) for r in self.storage.get("dataset", info["dataset_id"])["observations"]]
        return ModelPredictor(artifact, rows)

    def queue_forecast(self, request):
        with self.lock:
            turbines = self.assets(request.turbine_ids)
            request = request.model_copy(update={"turbine_ids": [t.id for t in turbines]})
            provider = DemoWeather() if request.weather_source == "demo" else ArchiveWeather(
                [WeatherSnapshot.model_validate(s) for s in self.storage.list("weather")])
            agent = ForecastAgent(provider, self.predictor(request.model_id))
            events = []
            snapshots, digest = agent.prepare(request, turbines, events.append)
            for stored in self.storage.list("forecast"):
                if stored["fingerprint"] == digest and stored["status"] != "failed":
                    return ForecastRun.model_validate(stored), None
            run = ForecastRun(id=f"run-{uuid4().hex}", created_at=now(), request=request,
                              status="queued", fingerprint=digest, events=events)
            self.storage.insert("forecast", run.model_dump(mode="json"))
            return run, (agent, turbines, snapshots)

    def execute_forecast(self, run_id, prepared):
        run = ForecastRun.model_validate(self.storage.get("forecast", run_id))
        if run.status != "queued":
            return run
        run.status = "running"
        self.storage.update_job("forecast", run.model_dump(mode="json"))

        def emit(event):
            run.events.append(event)
            self.storage.update_job("forecast", run.model_dump(mode="json"))

        try:
            agent, turbines, snapshots = prepared
            run.result = agent.predict(run.request, turbines, snapshots, run.fingerprint, emit)
            run.status = "succeeded"
        except ForecastError as exc:
            run.status, run.error = "failed", APIError(code=exc.code, message=str(exc))
        except Exception:
            logger.exception("Forecast %s failed", run.id)
            run.status, run.error = "failed", APIError(code="internal_error", message="Unexpected forecast error; see server log")
        self.storage.update_job("forecast", run.model_dump(mode="json"))
        return run

    def queue_backtest(self, request):
        self.assets(request.turbine_ids)
        predictor = self.predictor(request.model_id)
        if predictor.info.trained_through and predictor.info.trained_through > request.issued_at:
            raise ForecastError("model_from_future", "Model cutoff is after first replay issue")
        if request.actual_dataset_id:
            self.storage.get("dataset", request.actual_dataset_id)
        run = BacktestRun(id=f"backtest-{uuid4().hex}", created_at=now(), request=request, status="queued",
                          total=(request.end_issue_at - request.issued_at).days + 1,
                          demo=request.weather_source == "demo" or predictor.info.demo)
        self.storage.insert("backtest", run.model_dump(mode="json"))
        return run

    def execute_backtest(self, run_id):
        run = BacktestRun.model_validate(self.storage.get("backtest", run_id))
        run.status = "running"
        self.storage.update_job("backtest", run.model_dump(mode="json"))
        try:
            for offset in range(run.total):
                req = ForecastRequest(**{k: v for k, v in run.request.model_dump().items() if k in ForecastRequest.model_fields})
                req.issued_at += timedelta(days=offset)
                child, prepared = self.queue_forecast(req)
                if prepared:
                    child = self.execute_forecast(child.id, prepared)
                if child.status != "succeeded":
                    raise ForecastError("child_not_ready", f"Child {child.id}: {child.status}; retry replay when it completes")
                run.child_run_ids.append(child.id)
                run.completed += 1
                self.storage.update_job("backtest", run.model_dump(mode="json"))
            # Actuals are loaded only after every forecast was made.
            actuals = []
            if run.request.actual_dataset_id:
                actuals = [Observation.model_validate(r) for r in self.storage.get("dataset", run.request.actual_dataset_id)["observations"]]
            points = [point for _, point, _ in self.backtest_points(run)]
            run.metrics = evaluate(points, actuals)
            run.status = "succeeded"
        except ForecastError as exc:
            run.status, run.error = "failed", APIError(code=exc.code, message=str(exc))
        except Exception:
            logger.exception("Backtest %s failed", run.id)
            run.status, run.error = "failed", APIError(code="internal_error", message="Unexpected replay error; see server log")
        self.storage.update_job("backtest", run.model_dump(mode="json"))

    def backtest_points(self, run):
        for run_id in run.child_run_ids:
            child = ForecastRun.model_validate(self.storage.get("forecast", run_id))
            if child.result:
                weather = {s.turbine_id: s for s in child.result.weather}
                for point in child.result.points:
                    if run.request.evaluation_start <= point.valid_time < run.request.evaluation_end:
                        yield child, point, weather[point.turbine_id]

    def export(self, kind, identity):
        stored = self.storage.get(kind, identity)
        if stored["status"] != "succeeded":
            raise ForecastError("not_ready", "CSV is available only for successful jobs")
        actuals = {}
        if kind == "forecast":
            run = ForecastRun.model_validate(stored)
            snapshots = {s.turbine_id: s for s in run.result.weather}
            entries = [(run, p, snapshots[p.turbine_id]) for p in run.result.points]
        else:
            replay = BacktestRun.model_validate(stored)
            entries = self.backtest_points(replay)
            if replay.request.actual_dataset_id:
                rows = self.storage.get("dataset", replay.request.actual_dataset_id)["observations"]
                for row in rows:
                    p = Observation.model_validate(row)
                    actuals[(p.turbine_id, p.valid_time)] = p.power_normalized
        out = io.StringIO(newline="")
        writer = csv.writer(out)
        writer.writerow(["run_id", "issued_at", "turbine_id", "valid_time", "lead_hours", "power_normalized",
                         "actual_power_normalized", "model_id", "weather_id", "run_init", "available_at",
                         "verification", "demo", "fingerprint"])
        for run, point, snapshot in entries:
            writer.writerow([run.id, run.request.issued_at.isoformat(), point.turbine_id, point.valid_time.isoformat(),
                point.lead_hours, point.power_normalized, actuals.get((point.turbine_id, point.valid_time), ""),
                run.result.model.id, snapshot.id, snapshot.run_init.isoformat(),
                snapshot.available_at.isoformat() if snapshot.available_at else "", snapshot.verification,
                run.result.demo, run.fingerprint])
        return out.getvalue()
