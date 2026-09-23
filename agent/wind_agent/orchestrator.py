import asyncio
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime

from wind_contracts.models import (
    AgentEvent,
    ForecastRequest,
    ForecastResult,
    Turbine,
    WeatherSnapshot,
)

from wind_agent.interfaces import Predictor, TransientWeatherError, WeatherProvider
from wind_agent.weather import target_hours


class ForecastAgent:
    """Bounded policy-driven agent; no LLM or credentials required by the skeleton."""

    def __init__(self, weather: WeatherProvider, predictor: Predictor):
        self.weather = weather
        self.predictor = predictor

    async def prepare(self, request: ForecastRequest, turbines: list[Turbine], emit: Callable):
        def event(stage, message):
            emit(AgentEvent(at=datetime.now(UTC), stage=stage, message=message))

        event("validate", "Checking model cutoff, turbine IDs, and requested horizon")
        if {t.id for t in turbines} != set(request.turbine_ids):
            raise ValueError("Requested turbines do not match configured turbines")
        info = self.predictor.info
        if info.trained_through is not None and info.trained_through > request.issued_at:
            raise ValueError("Model training cutoff is later than the forecast issue time")
        snapshots = []
        for turbine in turbines:
            for attempt in range(3):
                try:
                    snapshot = await self.weather.fetch(turbine, request)
                    break
                except TransientWeatherError:
                    if attempt == 2:
                        raise
                    event("retry", f"Retry {attempt + 1}/2 for {turbine.id}")
                    await asyncio.sleep(0.25 * 2**attempt)
            self.validate_snapshot(snapshot, turbine, request)
            snapshots.append(snapshot)
            event("weather", f"Selected {snapshot.id} for {turbine.id} ({snapshot.verification})")
        return snapshots, fingerprint(request, snapshots, info.model_dump(mode="json"))

    @staticmethod
    def validate_snapshot(snapshot, turbine, request):
        if snapshot.turbine_id != turbine.id:
            raise ValueError("Weather snapshot belongs to a different turbine")
        if snapshot.available_at is None or snapshot.available_at > request.issued_at:
            raise ValueError("Weather was not available at the forecast issue time")
        if snapshot.run_init > request.issued_at:
            raise ValueError("Weather run is from the future")
        if request.weather_source == "archive" and (
            snapshot.verification != "verified" or snapshot.source == "demo"
        ):
            raise ValueError("Archive mode requires verified historical forecasts")
        if request.weather_source == "demo" and snapshot.verification != "synthetic":
            raise ValueError("Demo mode requires synthetic weather")
        if not set(target_hours(request)).issubset({point.valid_time for point in snapshot.points}):
            raise ValueError("Weather snapshot has missing forecast hours")

    async def run(self, request: ForecastRequest, turbines: list[Turbine], emit: Callable):
        snapshots, token = await self.prepare(request, turbines, emit)
        points = []
        targets = set(target_hours(request))
        for turbine, snapshot in zip(turbines, snapshots, strict=True):
            emit(
                AgentEvent(
                    at=datetime.now(UTC), stage="predict", message=f"Predicting {turbine.id}"
                )
            )
            weather = [point for point in snapshot.points if point.valid_time in targets]
            predicted = self.predictor.predict(turbine, weather, request.issued_at)
            # Enforce the plug-in contract even when a replacement model returns malformed rows.
            if [p.valid_time for p in predicted] != sorted(targets):
                raise ValueError(
                    "Predictor must return exactly one sorted point per requested hour"
                )
            for point in predicted:
                expected_lead = int((point.valid_time - request.issued_at).total_seconds() / 3600)
                if point.turbine_id != turbine.id or point.lead_hours != expected_lead:
                    raise ValueError("Predictor returned an incorrect turbine or lead time")
                if not 0 <= point.power_normalized <= 1:
                    raise ValueError("Predictor returned invalid normalized power")
            points.extend(predicted)
        warnings = []
        is_demo = request.weather_source == "demo" or self.predictor.info.is_demo
        if is_demo:
            warnings.append(
                "DEMO: synthetic weather and/or illustrative model; not competition results."
            )
        if self.predictor.info.algorithm == "binned-power-curve-v1":
            warnings.append(
                "Measured-wind baseline: forecast bias and height correction are not implemented."
            )
        if self.predictor.info.algorithm in {"persistence-v1", "catboost-scada-v1"}:
            warnings.append("SCADA-only model: weather values are not used by this predictor.")
        if any(
            t.hub_height_m is None or t.hub_height_m != s.wind_height_m
            for t, s in zip(turbines, snapshots, strict=True)
        ):
            warnings.append(
                "Hub-height matching is unverified; weather wind height is recorded per snapshot."
            )
        warnings.append("Output is normalized power. Uncertainty intervals are not calibrated yet.")
        emit(
            AgentEvent(
                at=datetime.now(UTC),
                stage="analyse",
                message="Checked hourly coverage, bounds, and provenance",
            )
        )
        result = ForecastResult(
            model_id=self.predictor.info.id,
            input_fingerprint=token,
            is_demo=is_demo,
            snapshots=snapshots,
            points=points,
            warnings=warnings,
        )
        emit(
            AgentEvent(
                at=datetime.now(UTC),
                stage="complete",
                message=f"Produced {len(points)} hourly predictions",
            )
        )
        return result


def fingerprint(request: ForecastRequest, snapshots: list[WeatherSnapshot], model: dict) -> str:
    # Retrieval time and record IDs do not change the physical/model input.
    weather = [
        snapshot.model_dump(mode="json", exclude={"id", "retrieved_at"}) for snapshot in snapshots
    ]
    raw = json.dumps(
        {"request": request.model_dump(mode="json"), "model": model, "weather": weather},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode()).hexdigest()
