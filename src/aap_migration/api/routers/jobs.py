from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from aap_migration.api.dependencies import get_app_state, get_db
from aap_migration.api.models import Job
from aap_migration.api.schemas import JobDetailResponse, JobResponse

router = APIRouter(tags=["jobs"])


@router.get("/jobs", response_model=list[JobResponse])
def list_jobs(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)) -> list[JobResponse]:
    jobs = db.query(Job).order_by(Job.started_at.desc()).limit(limit).all()
    return [JobResponse.model_validate(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobDetailResponse:
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobDetailResponse.model_validate(job)


@router.post("/jobs/{job_id}/cancel", status_code=204)
def cancel_job(job_id: str) -> None:
    state = get_app_state()
    if not state.job_service.cancel_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found or not running")
