from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from aap_migration.api.dependencies import get_app_state, get_db
from aap_migration.api.models import Connection, Job
from aap_migration.api.schemas import (
    JobCreatedResponse,
    MigratePreviewRequest,
    MigrateRunRequest,
    MigrationPreviewResponse,
)
from aap_migration.api.services.connection_service import ConnectionService
from aap_migration.config import (
    DEFAULT_SKIP_CREDENTIAL_NAMES,
    DEFAULT_SKIP_EXECUTION_ENVIRONMENT_NAMES,
)

router = APIRouter(tags=["migration"])
ACTIVE_JOB_STATUSES = ("running", "cancelling")


def _validate_migration_connections(source: Connection, dest: Connection) -> None:
    if source.id == dest.id:
        raise HTTPException(status_code=400, detail="Source and destination cannot be the same")
    if source.role != "source":
        raise HTTPException(status_code=400, detail="Source connection must have source role")
    if dest.role != "destination":
        raise HTTPException(status_code=400, detail="Destination connection must have destination role")


def _has_active_jobs(db: Session, job_types: tuple[str, ...]) -> bool:
    return (
        db.query(Job)
        .filter(Job.status.in_(ACTIVE_JOB_STATUSES), Job.type.in_(job_types))
        .first()
        is not None
    )


@router.post("/migrate/preview", response_model=JobCreatedResponse)
def start_preview(data: MigratePreviewRequest, db: Session = Depends(get_db)) -> JobCreatedResponse:
    svc = ConnectionService(db)
    source = svc.get(data.source_id)
    dest = svc.get(data.destination_id)
    if not source or not dest:
        raise HTTPException(status_code=404, detail="Connection not found")
    _validate_migration_connections(source, dest)
    state = get_app_state()
    from aap_migration.api.services.migration_service import MigrationService

    mig_svc = MigrationService(state.job_service, state.db_session_factory, state.loop)
    job_id = mig_svc.start_preview(source, dest)
    return JobCreatedResponse(job_id=job_id)


@router.get("/migrate/preview/{job_id}", response_model=MigrationPreviewResponse)
def get_preview(job_id: str) -> MigrationPreviewResponse:
    state = get_app_state()
    from aap_migration.api.services.migration_service import MigrationService

    mig_svc = MigrationService(state.job_service, state.db_session_factory, state.loop)
    preview = mig_svc.get_preview(job_id)
    if not preview:
        raise HTTPException(status_code=404, detail="Preview not found or not ready")
    return preview


@router.post("/migrate/run", response_model=JobCreatedResponse)
def run_migration(data: MigrateRunRequest, db: Session = Depends(get_db)) -> JobCreatedResponse:
    svc = ConnectionService(db)
    source = svc.get(data.source_id)
    dest = svc.get(data.destination_id)
    if not source or not dest:
        raise HTTPException(status_code=404, detail="Connection not found")
    _validate_migration_connections(source, dest)
    if _has_active_jobs(db, ("migration-run", "cleanup")):
        raise HTTPException(
            status_code=409,
            detail="Cannot start a migration while another migration or cleanup job is active",
        )
    state = get_app_state()
    from aap_migration.api.services.migration_service import MigrationService

    mig_svc = MigrationService(state.job_service, state.db_session_factory, state.loop)
    try:
        job_id = mig_svc.start_run(source, dest, data.job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JobCreatedResponse(job_id=job_id)


@router.post("/migrate/clear-state", status_code=200)
def clear_state(db: Session = Depends(get_db)) -> dict:
    """Clear migration state (progress records and ID mappings)."""
    import os

    from aap_migration.cli.commands.cleanup import clear_database

    active_jobs = (
        db.query(Job)
        .filter(Job.status.in_(ACTIVE_JOB_STATUSES))
        .count()
    )
    if active_jobs:
        raise HTTPException(
            status_code=409,
            detail="Cannot clear migration state while jobs are still running",
        )

    db_url = os.environ.get("MIGRATION_STATE_DB_PATH", "sqlite:///aap_bridge.db")
    cleared, deleted = clear_database(db_url)
    return {
        "cleared_progress": cleared,
        "deleted_mappings": deleted,
    }


@router.get("/exclusions")
def get_exclusions() -> dict:
    return {
        "migration": {
            "credentials": list(DEFAULT_SKIP_CREDENTIAL_NAMES),
            "execution_environments": list(DEFAULT_SKIP_EXECUTION_ENVIRONMENT_NAMES),
            "organizations": [],
        },
        "cleanup": {},
    }
