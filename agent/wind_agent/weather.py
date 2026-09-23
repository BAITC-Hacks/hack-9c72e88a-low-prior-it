import asyncio
import hashlib
import logging
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from wind_contracts.models import ForecastRequest, Turbine, WeatherPoint, WeatherSnapshot

from wind_agent.interfaces import TransientWeatherError, WeatherUnavailable


def target_hours(request: ForecastRequest) -> list[datetime]:
    return [request.issued_at + timedelta(hours=i) for i in range(1, request.horizon_hours + 1)]


class DemoWeatherProvider:
    """Deterministic artificial weather for development, never an archive substitute."""

    async def fetch(self, turbine: Turbine, request: ForecastRequest) -> WeatherSnapshot:
        seed = int(hashlib.sha256(turbine.id.encode()).hexdigest()[:8], 16) % 100
        points = []
        for moment in target_hours(request):
            phase = moment.timestamp() / 3600 + seed
            points.append(
                WeatherPoint(
                    valid_time=moment,
                    wind_speed_ms=round(8 + 3 * math.sin(phase / 7) + math.sin(phase / 2), 3),
                    wind_direction_deg=round((phase * 9) % 360, 2),
                    temperature_c=round(-5 + 6 * math.sin(phase / 24), 2),
                )
            )
        token = hashlib.sha256(
            f"{turbine.id}:{request.issued_at.isoformat()}:{request.horizon_hours}".encode()
        ).hexdigest()[:20]
        return WeatherSnapshot(
            id=f"demo-{token}",
            turbine_id=turbine.id,
            source="demo",
            weather_model="synthetic-v1",
            run_init=request.issued_at,
            retrieved_at=datetime.now(UTC),
            available_at=request.issued_at,
            verification="synthetic",
            wind_height_m=100,
            points=points,
        )


class ArchiveWeatherProvider:
    def __init__(self, load: Callable[[], list[WeatherSnapshot]]):
        self.load = load

    async def fetch(self, turbine: Turbine, request: ForecastRequest) -> WeatherSnapshot:
        targets = set(target_hours(request))
        candidates = [
            snapshot
            for snapshot in self.load()
            if snapshot.turbine_id == turbine.id
            and snapshot.source != "demo"
            and snapshot.verification == "verified"
            and snapshot.available_at is not None
            and snapshot.available_at <= request.issued_at
            and snapshot.run_init <= request.issued_at
            and targets.issubset({row.valid_time for row in snapshot.points})
        ]
        if not candidates:
            raise WeatherUnavailable(
                f"{turbine.id}: no verified archive available by {request.issued_at.isoformat()} "
                "covers every requested hour. Import a verified snapshot; demo fallback is disabled."
            )
        return max(candidates, key=lambda s: (s.run_init, s.available_at, s.retrieved_at))


async def download_single_run(
    turbine: Turbine,
    run_init: datetime,
    weather_model: str,
    client: httpx.AsyncClient | None = None,
) -> WeatherSnapshot:
    """Fetch a candidate archive. Publication provenance must be verified separately."""
    if turbine.latitude is None or turbine.longitude is None:
        raise ValueError("Configure verified turbine coordinates before downloading weather")
    params = {
        "latitude": turbine.latitude,
        "longitude": turbine.longitude,
        "models": weather_model,
        "run": run_init.astimezone(UTC).strftime("%Y-%m-%dT%H:%M"),
        "hourly": "wind_speed_100m,wind_direction_100m,temperature_2m",
        "wind_speed_unit": "ms",
        "timezone": "GMT",
        "forecast_days": 4,
    }

    async def retrieve(connection):
        for attempt in range(3):
            try:
                response = await connection.get(
                    "https://single-runs-api.open-meteo.com/v1/forecast", params=params
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise TransientWeatherError(f"Open-Meteo HTTP {response.status_code}")
                if response.is_error:
                    raise WeatherUnavailable(
                        f"Open-Meteo rejected the run (HTTP {response.status_code}); "
                        "check model/date coverage and variables."
                    )
                return response.json()
            except (httpx.TransportError, TransientWeatherError) as exc:
                logging.getLogger(__name__).warning("Weather attempt %s failed: %s", attempt + 1, exc)
                if attempt == 2:
                    raise TransientWeatherError("Open-Meteo unavailable after 3 attempts") from exc
                await asyncio.sleep(0.5 * 2**attempt)
        raise AssertionError("Unreachable")

    if client is None:
        async with httpx.AsyncClient(timeout=30) as connection:
            data = await retrieve(connection)
    else:
        data = await retrieve(client)
    try:
        units = data["hourly_units"]
        if units["wind_speed_100m"] != "m/s" or units["temperature_2m"] != "°C":
            raise ValueError("Unexpected weather units")
        if data.get("utc_offset_seconds") != 0:
            raise ValueError("Weather response must use UTC")
        hourly = data["hourly"]
        points = [
            WeatherPoint(
                valid_time=datetime.fromisoformat(moment).replace(tzinfo=UTC),
                wind_speed_ms=speed,
                wind_direction_deg=direction,
                temperature_c=temperature,
            )
            for moment, speed, direction, temperature in zip(
                hourly["time"],
                hourly["wind_speed_100m"],
                hourly["wind_direction_100m"],
                hourly["temperature_2m"],
                strict=True,
            )
            if datetime.fromisoformat(moment).replace(tzinfo=UTC) >= run_init
        ]
        return WeatherSnapshot(
            id=f"weather-{uuid4().hex}",
            turbine_id=turbine.id,
            source="open-meteo-single-run",
            weather_model=weather_model,
            run_init=run_init,
            retrieved_at=datetime.now(UTC),
            verification="unverified",
            wind_height_m=100,
            points=points,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WeatherUnavailable(f"Invalid Open-Meteo response: {exc}") from exc
