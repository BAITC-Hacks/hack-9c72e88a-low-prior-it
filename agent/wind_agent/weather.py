"""Explicit demo weather, strict archive selection and unverified downloads."""
import hashlib
import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from pydantic import ValidationError

from wind_contracts import Event, ForecastRequest, Turbine, WeatherFetch, WeatherPoint, WeatherSnapshot

from .interfaces import Emit, ForecastError


def emit_event(emit: Emit, step: str, message: str):
    emit(Event(at=datetime.now(timezone.utc), step=step, message=message))


def target_times(request: ForecastRequest):
    return [request.issued_at + timedelta(hours=h) for h in range(1, request.horizon_hours + 1)]


def eligible(snapshot: WeatherSnapshot, request: ForecastRequest) -> bool:
    return (snapshot.verification == "verified" and snapshot.kind == "forecast"
            and bool(snapshot.availability_evidence.strip()) and snapshot.available_at is not None
            and snapshot.available_at <= request.issued_at and snapshot.run_init <= request.issued_at)


class DemoWeather:
    def get(self, request: ForecastRequest, turbine: Turbine, emit: Emit) -> WeatherSnapshot:
        phase = int(hashlib.sha256(turbine.id.encode()).hexdigest()[:6], 16) / 1000
        points = []
        for t in target_times(request):
            h = t.timestamp() / 3600
            points.append(WeatherPoint(valid_time=t,
                wind_speed_ms=8 + 3 * math.sin(h / 7 + phase) + math.cos(h / 19),
                temperature_c=4 + 7 * math.sin(h / 24), wind_direction_deg=(h * 7 + phase) % 360))
        emit_event(emit, "weather", f"{turbine.id}: synthetic demo weather; not a historical forecast")
        return WeatherSnapshot(id=f"demo-{turbine.id}-{int(request.issued_at.timestamp())}",
            turbine_id=turbine.id, source="Deterministic synthetic demo", weather_model="demo-v1",
            kind="synthetic", verification="demo", run_init=request.issued_at,
            available_at=request.issued_at, retrieved_at=request.issued_at, wind_height_m=100,
            points=points)


class ArchiveWeather:
    def __init__(self, snapshots: list[WeatherSnapshot]):
        self.snapshots = snapshots

    def get(self, request: ForecastRequest, turbine: Turbine, emit: Emit) -> WeatherSnapshot:
        candidates = sorted((s for s in self.snapshots if s.turbine_id == turbine.id and eligible(s, request)),
                            key=lambda s: (s.run_init, s.available_at, s.retrieved_at, s.id), reverse=True)
        need = target_times(request)
        for snapshot in candidates:
            by_time = {p.valid_time: p for p in snapshot.points}
            missing = set(need) - set(by_time)
            if missing:
                emit_event(emit, "fallback", f"Skipped {snapshot.id}: missing {len(missing)} required hours")
                continue
            emit_event(emit, "weather", f"Selected {snapshot.id}; published {snapshot.available_at.isoformat()}")
            return snapshot.model_copy(update={"points": [by_time[t] for t in need]})
        raise ForecastError("archive_unavailable", f"{turbine.id}: no verified forecast with full coverage available at issue time")


class SingleRunsAdapter:
    URL = "https://single-runs-api.open-meteo.com/v1/forecast"

    def __init__(self, cache_dir: Path, client: httpx.Client | None = None, sleep=time.sleep):
        self.cache_dir, self.client, self.sleep = cache_dir, client, sleep

    def fetch(self, request: WeatherFetch, turbine: Turbine, emit: Emit = lambda event: None):
        if turbine.latitude is None or turbine.longitude is None:
            raise ForecastError("coordinates_missing", "Configure confirmed turbine coordinates", 422)
        if request.run_init > datetime.now(timezone.utc):
            raise ForecastError("future_run", "Model initialization is in the future", 422)
        params = {"latitude": turbine.latitude, "longitude": turbine.longitude,
            "models": request.weather_model, "run": request.run_init.strftime("%Y-%m-%dT%H:%M"),
            "hourly": "wind_speed_100m,temperature_2m,wind_direction_100m", "forecast_hours": 96,
            "wind_speed_unit": "ms", "timezone": "GMT"}
        client = self.client or httpx.Client(timeout=45)
        try:
            for attempt in range(3):
                try:
                    response = client.get(self.URL, params=params)
                    if response.status_code == 429 or response.status_code >= 500:
                        raise httpx.TransportError(f"provider HTTP {response.status_code}")
                    response.raise_for_status()
                    payload = response.json()
                    break
                except httpx.TransportError as exc:
                    logging.getLogger(__name__).warning("Weather attempt %s failed: %s", attempt + 1, exc)
                    emit_event(emit, "retry", f"Weather attempt {attempt + 1} failed: {exc}")
                    if attempt == 2:
                        raise ForecastError("weather_transport", "Weather service unavailable after 3 attempts", 503) from exc
                    self.sleep(2 ** attempt)
                except (httpx.HTTPStatusError, ValueError) as exc:
                    raise ForecastError("weather_response", "Weather provider rejected request or returned invalid JSON", 422) from exc
        finally:
            if self.client is None:
                client.close()
        retrieved = datetime.now(timezone.utc)
        key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        raw_path = self.cache_dir / f"{key}-{uuid4().hex}.json"
        raw_path.write_text(json.dumps({"url": self.URL, "params": params, "retrieved_at": retrieved.isoformat(),
                                       "response": payload}, ensure_ascii=False), encoding="utf-8")
        try:
            units = payload["hourly_units"]
            if units["wind_speed_100m"] != "m/s" or units["temperature_2m"] != "°C" or units["wind_direction_100m"] != "°":
                raise ValueError("unexpected weather units")
            if payload.get("utc_offset_seconds", 0) != 0:
                raise ValueError("provider timezone is not UTC")
            hourly = payload["hourly"]
            keys = ("wind_speed_100m", "temperature_2m", "wind_direction_100m")
            if any(len(hourly[k]) != len(hourly["time"]) for k in keys):
                raise ValueError("weather arrays have different lengths")
            points = []
            for i, stamp in enumerate(hourly["time"]):
                if any(hourly[k][i] is None for k in keys):
                    continue  # Preserve holes: archive selection rejects incomplete target windows.
                t = datetime.fromisoformat(stamp)
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                points.append(WeatherPoint(valid_time=t, wind_speed_ms=hourly[keys[0]][i],
                    temperature_c=hourly[keys[1]][i], wind_direction_deg=hourly[keys[2]][i]))
            return WeatherSnapshot(id=f"weather-{uuid4().hex}", turbine_id=turbine.id,
                source=self.URL, weather_model=request.weather_model, run_init=request.run_init,
                retrieved_at=retrieved, wind_height_m=100, points=points,
                preparation=f"Raw response: {raw_path.name}. Null hours omitted; no interpolation. Original forecast lineage unverified.")
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise ForecastError("weather_response", f"Invalid weather response: {exc}", 422) from exc
