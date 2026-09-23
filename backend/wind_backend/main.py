import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from wind_agent.interfaces import ForecastError
from wind_agent.weather import SingleRunsAdapter
from wind_contracts import APIError, Turbine

from .routes import router
from .service import Service
from .storage import Storage

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def create_app(db_path=None, turbine_path=None, adapter=None):
    @asynccontextmanager
    async def lifespan(app):
        config = Path(turbine_path or os.getenv("WINDFARM_TURBINES", str(ROOT / "config/turbines.example.json")))
        turbines = [Turbine.model_validate(t) for t in json.loads(config.read_text(encoding="utf-8"))]
        if len({t.id for t in turbines}) != len(turbines) or not turbines:
            raise ValueError("Turbine configuration must contain unique IDs")
        storage = Storage(db_path or os.getenv("WINDFARM_DB", str(ROOT / "data/windfarm.sqlite")))
        app.state.service = Service(storage, turbines, adapter or SingleRunsAdapter(
            Path(os.getenv("WINDFARM_WEATHER_CACHE", str(ROOT / "data/weather/candidates")))))
        yield
        storage.close()

    app = FastAPI(title="Low Prior Wind", version="1.0.0", lifespan=lifespan,
                  responses={code: {"model": APIError} for code in (404, 409, 422, 503)})

    @app.exception_handler(ForecastError)
    async def domain_error(request: Request, exc: ForecastError):
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        message = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return JSONResponse(status_code=422, content={"code": "validation_error", "message": message})

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"code": "http_error", "message": str(exc.detail)})

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logging.getLogger(__name__).error("Unexpected API error", exc_info=exc)
        return JSONResponse(status_code=500, content={"code": "internal_error", "message": "Unexpected server error; see server log"})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "low-prior-wind"}

    app.include_router(router)
    return app


app = create_app()
