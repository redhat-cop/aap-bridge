import threading
from typing import Any


class JobService:
    MAX_LOG_LINES = 4000
    LOG_TRIM_BATCH = 500
    MAX_FINISHED_JOBS = 50

    def __init__(self) -> None:
        self._log_buffers: dict[str, list[str]] = {}
        self._log_starts: dict[str, int] = {}
        self._tasks: dict[str, Any] = {}
        self._statuses: dict[str, dict] = {}
        self._finished_jobs: list[str] = []
        self._lock = threading.Lock()

    def register_job(self, job_id: str) -> None:
        with self._lock:
            self._log_buffers[job_id] = []
            self._log_starts[job_id] = 0
            self._statuses[job_id] = {"status": "running"}

    def append_log(self, job_id: str, line: str) -> None:
        with self._lock:
            if job_id in self._log_buffers:
                buffer = self._log_buffers[job_id]
                buffer.append(line)
                if len(buffer) > self.MAX_LOG_LINES:
                    trim = min(self.LOG_TRIM_BATCH, len(buffer) - self.MAX_LOG_LINES)
                    del buffer[:trim]
                    self._log_starts[job_id] = self._log_starts.get(job_id, 0) + trim

    def get_logs_since(self, job_id: str, offset: int) -> list[str]:
        with self._lock:
            buf = self._log_buffers.get(job_id, [])
            start = self._log_starts.get(job_id, 0)
            relative_offset = max(offset - start, 0)
            return buf[relative_offset:]

    def get_log_start(self, job_id: str) -> int:
        with self._lock:
            return self._log_starts.get(job_id, 0)

    def get_job_status(self, job_id: str) -> dict | None:
        with self._lock:
            return self._statuses.get(job_id)

    def mark_completed(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._statuses:
                self._statuses[job_id] = {"status": "completed"}
            self._tasks.pop(job_id, None)
            self._remember_finished_job(job_id)

    def mark_failed(self, job_id: str, error: str) -> None:
        with self._lock:
            if job_id in self._statuses:
                self._statuses[job_id] = {"status": "failed", "error": error}
            self._tasks.pop(job_id, None)
            self._remember_finished_job(job_id)

    def mark_cancelled(self, job_id: str, message: str = "Cancelled") -> None:
        with self._lock:
            if job_id in self._statuses:
                self._statuses[job_id] = {"status": "cancelled", "error": message}
            self._tasks.pop(job_id, None)
            self._remember_finished_job(job_id)

    def register_task(self, job_id: str, task: Any) -> None:
        with self._lock:
            self._tasks[job_id] = task

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(job_id)
            if not task:
                return False
            task.cancel()
            if job_id in self._statuses:
                self._statuses[job_id] = {"status": "cancelling"}
            return True

    def _remember_finished_job(self, job_id: str) -> None:
        if job_id in self._finished_jobs:
            self._finished_jobs.remove(job_id)
        self._finished_jobs.append(job_id)
        while len(self._finished_jobs) > self.MAX_FINISHED_JOBS:
            expired_job_id = self._finished_jobs.pop(0)
            self._log_buffers.pop(expired_job_id, None)
            self._log_starts.pop(expired_job_id, None)
            self._statuses.pop(expired_job_id, None)
