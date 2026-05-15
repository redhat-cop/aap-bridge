from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from aap_migration.api.dependencies import get_app_state, get_db
from aap_migration.api.models import Job
from aap_migration.api.schemas import JobCreatedResponse
from aap_migration.api.services.connection_service import ConnectionService

router = APIRouter(tags=["operations"])
ACTIVE_JOB_STATUSES = ("running", "cancelling")


def _has_active_jobs(
    db: Session,
    job_types: tuple[str, ...],
    connection_id: str | None = None,
) -> bool:
    query = db.query(Job).filter(Job.status.in_(ACTIVE_JOB_STATUSES), Job.type.in_(job_types))
    if connection_id is not None:
        query = query.filter(Job.connection_id == connection_id)
    return query.first() is not None


@router.post("/connections/{connection_id}/cleanup", response_model=JobCreatedResponse)
def run_cleanup(connection_id: str, db: Session = Depends(get_db)) -> JobCreatedResponse:
    svc = ConnectionService(db)
    conn = svc.get(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    if conn.role != "destination" or conn.type != "aap":
        raise HTTPException(
            status_code=400,
            detail="Cleanup is only supported for AAP destination connections",
        )
    if _has_active_jobs(db, ("migration-run", "cleanup", "export")):
        raise HTTPException(
            status_code=409,
            detail="Cannot start cleanup while migration, export, or cleanup jobs are active",
        )
    state = get_app_state()
    from aap_migration.api.services.operation_service import OperationService

    op_svc = OperationService(state.job_service, state.db_session_factory, state.loop)
    job_id = op_svc.start_cleanup(conn)
    return JobCreatedResponse(job_id=job_id)


@router.post("/connections/{connection_id}/export", response_model=JobCreatedResponse)
def run_export(connection_id: str, db: Session = Depends(get_db)) -> JobCreatedResponse:
    svc = ConnectionService(db)
    conn = svc.get(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    if _has_active_jobs(db, ("export", "cleanup"), connection_id=connection_id):
        raise HTTPException(
            status_code=409,
            detail="Cannot start another export while an export or cleanup job is active for this connection",
        )
    state = get_app_state()
    from aap_migration.api.services.operation_service import OperationService

    op_svc = OperationService(state.job_service, state.db_session_factory, state.loop)
    job_id = op_svc.start_export(conn)
    return JobCreatedResponse(job_id=job_id)
