import hashlib
import json

from wind_contracts import ForecastRequest, ForecastResult, Turbine

from .interfaces import Emit, ForecastError, Predictor, WeatherProvider
from .weather import eligible, emit_event, target_times


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class ForecastAgent:
    def __init__(self, weather: WeatherProvider, predictor: Predictor):
        self.weather, self.predictor = weather, predictor

    def prepare(self, request: ForecastRequest, turbines: list[Turbine], emit: Emit):
        info = self.predictor.info
        if info.trained_through and info.trained_through > request.issued_at:
            raise ForecastError("model_from_future", "Model training cutoff is after forecast issue time")
        if {t.id for t in turbines} != set(request.turbine_ids):
            raise ForecastError("unknown_turbine", "Requested turbines do not match configured assets", 404)
        if info.turbine_ids and not set(request.turbine_ids) <= set(info.turbine_ids):
            raise ForecastError("untrained_turbine", "Model has no training data for a selected turbine")
        emit_event(emit, "validate", "Validated model cutoff, assets and issue time")
        snapshots = [self.weather.get(request, t, emit) for t in turbines]
        for s, t in zip(snapshots, turbines):
            if s.turbine_id != t.id or [p.valid_time for p in s.points] != target_times(request):
                raise ForecastError("weather_coverage", "Weather does not match turbine and hourly horizon")
            if request.weather_source == "archive" and not eligible(s, request):
                raise ForecastError("weather_from_future", "Unverified or late weather is forbidden in archive mode")
        # IDs, retrieval times and evidence are part of auditable input identity.
        digest = fingerprint({"request": request.model_dump(mode="json"), "assets": [t.model_dump(mode="json") for t in turbines],
            "weather": [s.model_dump(mode="json") for s in snapshots], "model": info.model_dump(mode="json")})
        return snapshots, digest

    def run(self, request: ForecastRequest, turbines: list[Turbine], emit: Emit) -> ForecastResult:
        snapshots, digest = self.prepare(request, turbines, emit)
        return self.predict(request, turbines, snapshots, digest, emit)

    def predict(self, request, turbines, snapshots, digest, emit):
        points = []
        warnings = list(self.predictor.info.warnings)
        for turbine, snapshot in zip(turbines, snapshots):
            output = self.predictor.predict(turbine, snapshot, request.issued_at)
            if ([p.valid_time for p in output] != target_times(request)
                    or any(p.turbine_id != turbine.id or p.lead_hours != i + 1 for i, p in enumerate(output))):
                raise ForecastError("prediction_coverage", "Predictor returned an invalid hourly horizon")
            points.extend(output)
            if turbine.hub_height_m != snapshot.wind_height_m:
                warnings.append(f"{turbine.id}: {snapshot.wind_height_m:g} m wind has not been adjusted to confirmed hub height")
            if max(p.wind_speed_ms for p in snapshot.points) >= 20:
                warnings.append(f"{turbine.id}: strong wind; shutdown behavior is not modeled")
        demo = request.weather_source == "demo" or self.predictor.info.demo
        if demo:
            warnings.append("DEMO: synthetic weather and/or artificial model; not a competition forecast")
        emit_event(emit, "predict", f"Computed {len(points)} hourly predictions")
        emit_event(emit, "analyse", f"Checked coverage and physical bounds; {len(warnings)} warnings")
        return ForecastResult(points=points, weather=snapshots, model=self.predictor.info,
                              demo=demo, fingerprint=digest, warnings=warnings)
