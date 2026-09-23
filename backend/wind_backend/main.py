from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from wind_agent.interfaces import TransientWeatherError, WeatherUnavailable
from wind_contracts.models import ApiError, Health

from wind_backend.config import Settings
from wind_backend.routes import router
from wind_backend.service import DomainError, WindService
from wind_backend.storage import Repository


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application):
        service = WindService(Repository(settings.db_path), settings.turbines())
        service.recover_interrupted_jobs()
        application.state.service = service
        yield

    application = FastAPI(
        title="Low Prior Wind API",
        version="0.1.0",
        description="Hourly normalized turbine-power forecasts, auditable weather, and rolling replay.",
        lifespan=lifespan,
        responses={status: {"model": ApiError} for status in (404, 409, 422, 503)},
    )

    @application.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError):
        return JSONResponse(
            status_code=exc.status, content={"code": exc.code, "message": exc.message}
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        message = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return JSONResponse(
            status_code=422, content={"code": "validation_error", "message": message}
        )

    @application.exception_handler(ValueError)
    async def value_error(_: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"code": "invalid_input", "message": str(exc)})

    @application.exception_handler(WeatherUnavailable)
    async def weather_error(_: Request, exc: WeatherUnavailable):
        return JSONResponse(
            status_code=409, content={"code": "weather_unavailable", "message": str(exc)}
        )

    @application.exception_handler(TransientWeatherError)
    async def transient_error(_: Request, exc: TransientWeatherError):
        return JSONResponse(
            status_code=503, content={"code": "weather_transport_error", "message": str(exc)}
        )

    @application.get("/health", response_model=Health, tags=["Health"])
    def health():
        return Health()

    application.include_router(router)
    return application


app = create_app()
