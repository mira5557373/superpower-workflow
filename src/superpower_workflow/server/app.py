from __future__ import annotations

import hmac
import importlib
import logging
import time
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from superpower_workflow.server.config import ServerConfig

logger = logging.getLogger(__name__)

_MAX_RATE_BUCKETS = 10_000


def create_app(config: ServerConfig | None = None) -> FastAPI:
    if config is None:
        from superpower_workflow.server.config import load_server_config

        config = load_server_config()

    app = FastAPI(
        title="Superpower Workflow API",
        version="1.0.0",
        docs_url="/docs" if not config.api_key else None,
        redoc_url=None,
    )

    app.state.config = config
    app.state.engine = None

    if config.database_url:
        try:
            from superpower_workflow.db.engine import create_engine_from_url
            from superpower_workflow.db.models import Base

            app.state.engine = create_engine_from_url(config.database_url)
            Base.metadata.create_all(app.state.engine)
        except Exception:
            logger.warning("Failed to initialize database", exc_info=True)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _rate_buckets: dict[str, list[float]] = defaultdict(list)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        if request.url.path == "/api/v1/health" or request.url.path == "/":
            return await call_next(request)

        if config.api_key:
            auth = request.headers.get("Authorization", "")
            token = auth[7:] if auth.startswith("Bearer ") else ""
            if not hmac.compare_digest(token, config.api_key):
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        if len(_rate_buckets) > _MAX_RATE_BUCKETS:
            _rate_buckets.clear()
        bucket = _rate_buckets[client_ip]
        bucket[:] = [t for t in bucket if now - t < 60]
        if len(bucket) >= config.rate_limit_per_minute:
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
        bucket.append(now)

        return await call_next(request)

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/api/v1/health")
    def health():
        db_status = "not_configured"
        if app.state.engine is not None:
            try:
                with app.state.engine.connect() as conn:
                    conn.exec_driver_sql("SELECT 1")
                db_status = "connected"
            except Exception:
                db_status = "error"
        return {"status": "ok", "db": db_status}

    _router_modules = [
        "superpower_workflow.server.routers.projects",
        "superpower_workflow.server.routers.runs",
        "superpower_workflow.server.routers.milestones",
        "superpower_workflow.server.routers.events",
        "superpower_workflow.server.routers.metrics",
        "superpower_workflow.server.routers.ws",
    ]
    for mod_name in _router_modules:
        try:
            mod = importlib.import_module(mod_name)
            app.include_router(mod.router)
        except (ImportError, AttributeError):
            pass

    return app
