import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from aap_migration.api.dependencies import set_app_state
from aap_migration.api.models import Base, Job
from aap_migration.api.routers import connections, jobs, migration, operations, resources
from aap_migration.api.services.job_service import JobService
from aap_migration.api.websocket import router as ws_router

_db_url: str = ""


@dataclass
class AppState:
    db_session_factory: sessionmaker[Session] = field(init=False)
    job_service: JobService = field(init=False)
    loop: asyncio.AbstractEventLoop = field(init=False)

    def __post_init__(self) -> None:
        self.job_service = JobService()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    engine = create_engine(_db_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)

    from aap_migration.migration.models import Base as MigrationBase

    MigrationBase.metadata.create_all(engine)

    state = AppState()
    state.db_session_factory = sessionmaker(bind=engine)
    state.loop = asyncio.get_running_loop()
    db = state.db_session_factory()
    try:
        stale_jobs = (
            db.query(Job)
            .filter(Job.status.in_(("running", "cancelling")))
            .all()
        )
        if stale_jobs:
            finished_at = datetime.now(UTC)
            for job in stale_jobs:
                job.status = "failed"
                job.finished_at = finished_at
                job.error = job.error or "API restarted before the job completed"
            db.commit()
    finally:
        db.close()
    set_app_state(state)
    yield
    engine.dispose()


def create_app(db_url: str = "") -> FastAPI:
    global _db_url
    _db_url = db_url or os.environ.get("MIGRATION_STATE_DB_PATH", "sqlite:///aap_bridge.db")

    app = FastAPI(
        title="AAP Bridge",
        description="Web API for AAP Bridge migration tool",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(connections.router, prefix="/api")
    app.include_router(resources.router, prefix="/api")
    app.include_router(operations.router, prefix="/api")
    app.include_router(migration.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(ws_router)

    return app
