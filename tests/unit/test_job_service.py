from aap_migration.api.services.job_service import JobService


class DummyTask:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


def test_cancel_job_marks_job_as_cancelling_until_worker_finishes():
    svc = JobService()
    task = DummyTask()

    svc.register_job("job-1")
    svc.register_task("job-1", task)  # type: ignore[arg-type]

    assert svc.cancel_job("job-1") is True
    assert task.cancelled is True
    assert svc.get_job_status("job-1") == {"status": "cancelling"}

    svc.mark_cancelled("job-1")

    assert svc.get_job_status("job-1") == {"status": "cancelled", "error": "Cancelled"}


def test_append_log_trims_old_entries():
    svc = JobService()
    svc.register_job("job-2")

    for idx in range(JobService.MAX_LOG_LINES + JobService.LOG_TRIM_BATCH + 10):
        svc.append_log("job-2", f"line-{idx}")

    logs = svc.get_logs_since("job-2", 0)

    assert len(logs) == JobService.MAX_LOG_LINES
    assert logs[0] == f"line-{JobService.LOG_TRIM_BATCH + 10}"
    assert logs[-1] == f"line-{JobService.MAX_LOG_LINES + JobService.LOG_TRIM_BATCH + 9}"


def test_finished_job_pruning_removes_in_memory_status():
    svc = JobService()

    for idx in range(JobService.MAX_FINISHED_JOBS + 1):
        job_id = f"job-{idx}"
        svc.register_job(job_id)
        svc.mark_completed(job_id)

    assert svc.get_job_status("job-0") is None
    assert svc.get_job_status(f"job-{JobService.MAX_FINISHED_JOBS}") == {"status": "completed"}
