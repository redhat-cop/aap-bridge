import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from aap_migration.api.dependencies import get_app_state
from aap_migration.api.models import Job

router = APIRouter()


@router.websocket("/ws/jobs/{job_id}/logs")
async def stream_logs(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    state = get_app_state()
    offset = 0
    try:
        while True:
            log_start = state.job_service.get_log_start(job_id)
            if offset < log_start:
                offset = log_start
            lines = state.job_service.get_logs_since(job_id, offset)
            for line in lines:
                await websocket.send_text(line)
                offset += 1
            job = state.job_service.get_job_status(job_id)
            if job is None:
                db = state.db_session_factory()
                try:
                    persisted_job = db.query(Job).filter(Job.id == job_id).first()
                finally:
                    db.close()

                if not persisted_job:
                    await websocket.close(code=1008, reason="not_found")
                    return

                persisted_lines = list(persisted_job.output or [])
                for line in persisted_lines[offset:]:
                    await websocket.send_text(line)
                    offset += 1

                if persisted_job.status in ("completed", "failed", "cancelled"):
                    await websocket.close(code=1000, reason=persisted_job.status)
                else:
                    await websocket.close(code=1011, reason="job_unavailable")
                return
            if job and job["status"] in ("completed", "failed", "cancelled") and not lines:
                await websocket.close(code=1000, reason=job["status"])
                return
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        pass
