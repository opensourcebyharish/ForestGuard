"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from forestguard.config import get_settings
from forestguard.database import check_database, initialize_database
from forestguard.notifications import NotificationWorker
from forestguard.routes.alerts import router as alerts_router
from forestguard.routes.commands import router as commands_router
from forestguard.routes.nodes import router as nodes_router
from forestguard.routes.readings import router as readings_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    initialize_database(settings.database_path)
    worker = NotificationWorker(settings.database_path, settings)
    worker.start()
    try:
        yield
    finally:
        worker.stop()


app = FastAPI(title="ForestGuard", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(nodes_router)
app.include_router(readings_router)
app.include_router(alerts_router)
app.include_router(commands_router)


@app.get("/")
def root() -> dict[str, str]:
    """Describe the service without exposing runtime configuration."""
    return {"name": "ForestGuard", "status": "running", "docs": "/docs"}


@app.get("/health")
def health() -> dict[str, str]:
    """Report application and SQLite availability for local monitoring."""
    database_ok = check_database(get_settings().database_path)
    return {
        "status": "ok" if database_ok else "degraded",
        "database": "ok" if database_ok else "unavailable",
    }
