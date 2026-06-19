import asyncio
import contextvars
import logging
import re
import time
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from aap_migration.api.models import Connection, Job
from aap_migration.api.schemas import MigrationPreviewResponse
from aap_migration.api.services.job_service import JobService

ACTIVE_JOB_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "migration_service_active_job_id",
    default="",
)


class JobContextFilter(logging.Filter):
    def __init__(self, job_id: str) -> None:
        super().__init__()
        self.job_id = job_id

    def filter(self, record: logging.LogRecord) -> bool:
        return ACTIVE_JOB_ID.get() == self.job_id


class JobLogHandler(logging.Handler):
    def __init__(self, job_service: JobService, job_id: str) -> None:
        super().__init__()
        self.job_service = job_service
        self.job_id = job_id
        self._phase = ""
        self._phase_desc = ""
        self._exported = 0
        self._created = 0
        self._skipped = 0
        self._failed = 0
        self._phase_start = 0.0
        self._last_emitted = 0
        self._total_created = 0
        self._total_skipped = 0
        self._total_failed = 0
        self._phase_num = 0
        self._total_phases = 0

    def _log(self, msg: str) -> None:
        self.job_service.append_log(self.job_id, msg)

    # Matches structlog wire format:
    # "TIMESTAMP [LEVEL   ] EVENT_NAME [logger.name] key=val ..."
    _STRUCTLOG_RE = re.compile(
        r"\d{4}-\d{2}-\d{2}T[\d:.]+Z\s+\[\w+\s*\]\s+(\S+)\s+\[[\w.]+\]\s*(.*)"
    )

    def _format_warning(self, msg: str) -> str:
        """Extract event name and key=value pairs from a structlog-formatted warning."""
        m = self._STRUCTLOG_RE.match(msg)
        if m:
            event = m.group(1)
            rest = re.sub(r"\b(?:app|version)=\S+\s*", "", m.group(2)).strip()
            return f"{event}: {rest}" if rest else event
        return msg.split("version=")[0].strip() if "version=" in msg else msg

    def _finish_phase(self) -> None:
        """Update running totals and reset per-phase counters.

        Progress output is handled by LogMigrationProgressDisplay; this only
        maintains the aggregate counters used for the migration_completed summary.
        """
        self._total_created += self._created
        self._total_skipped += self._skipped
        self._total_failed += self._failed
        self._exported = 0
        self._created = 0
        self._skipped = 0
        self._failed = 0
        self._last_emitted = 0
        self._phase_start = 0.0

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)

        # --- Phase lifecycle ---
        if "migration_started" in msg:
            self._total_phases = int(self._extract("total_phases=", msg) or "0")
            self._log(f"Migration started ({self._total_phases} phases)")
            return

        if "phase_starting" in msg:
            self._finish_phase()
            self._phase_num += 1
            desc = self._extract("description=", msg)
            self._phase_desc = desc or "unknown"
            self._exported = 0
            self._created = 0
            self._skipped = 0
            self._failed = 0
            self._last_emitted = 0
            self._phase_start = time.time()
            self._log(f"\n[{self._phase_num}/{self._total_phases}] {self._phase_desc}")
            return

        if "phase_completed" in msg:
            self._finish_phase()
            return

        if "phase_failed" in msg:
            self._finish_phase()
            return

        if "migration_completed" in msg or "migration_failed" in msg:
            self._log(
                f"\nMigration complete: "
                f"{self._total_created} created, "
                f"{self._total_skipped} skipped, "
                f"{self._total_failed} failed"
            )
            return

        # --- Export counts ---
        if "export_completed" in msg:
            exported_str = self._extract("total_exported=", msg)
            resource_type = self._extract("resource_type=", msg)
            if exported_str:
                n = int(exported_str)
                if n > 0:
                    label = f" {resource_type}" if resource_type else ""
                    self._log(f"  ✓{label}: {n} resource{'s' if n != 1 else ''} exported")
            return

        # --- Import progress ---
        if "resource_import_failed" in msg:
            self._failed += 1
            name = self._extract("source_name=", msg) or self._extract("source_id=", msg)
            err = self._extract("error=", msg)[:80] if "error=" in msg else ""
            self._log(f"  ✗ Failed: {name} — {err}")
            return

        if "resource_skipped" in msg or "resources_skipped_summary" in msg:
            if "skipped_count=" in msg:
                cnt = int(self._extract("skipped_count=", msg) or "1")
                self._skipped += cnt
            else:
                self._skipped += 1
            return

        if "resource_created" in msg:
            self._created += 1
            return

        # --- Suppress noisy events ---
        noisy = (
            "api_request",
            "Marked resource",
            "_creating",
            "_created",
            "credential_creating",
            "credential_created",
            "resource_creating",
            "transforming_resource",
            # One clear message is logged by _run_transform_command before the
            # parallel workers start; suppress the per-worker repetitions.
            "schema_comparison_file_not_found",
            # unresolved_dependency: auto-created inventory sources reference parent
            # inventories that are imported in a later phase (smart/constructed);
            # AAP recreates them on next sync. EE dependencies are pre-seeded in the
            # transform step so real EE issues don't reach this point.
            "unresolved_dependency",
            # survey_spec_import_failed: AAP 2.6 rejects the empty survey spec the
            # importer sends for templates without surveys; templates with surveys
            # still import correctly via a separate API call.
            "survey_spec_import_failed",
            # Team membership via the old POST endpoint is not supported in AAP 2.6
            # RBAC; memberships are established correctly through role assignments.
            "user_team_membership_skipped_unmapped_team",
            "team_member_link_failed",
            "user_team_membership_link_failed",
            # Role assignments have no 'name' field; deduplication logs this but
            # everything still imports correctly.
            "no_identifiers_found",
        )
        for n in noisy:
            if n in msg:
                return

        # --- Show warnings/errors ---
        if record.levelno >= logging.WARNING:
            clean = self._format_warning(msg)
            if len(clean) > 300:
                clean = clean[:300] + "..."
            self._log(f"  ⚠ {clean}")

    @staticmethod
    def _extract(prefix: str, msg: str) -> str:
        if prefix not in msg:
            return ""
        start = msg.index(prefix) + len(prefix)
        end = msg.find(" ", start)
        if end == -1:
            end = len(msg)
        return msg[start:end].strip()


class MigrationService:
    def __init__(
        self,
        job_service: JobService,
        session_factory: sessionmaker[Session],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.job_service = job_service
        self.session_factory = session_factory
        self.loop = loop

    def _get_db_url(self) -> str:
        import os

        return os.environ.get("MIGRATION_STATE_DB_PATH", "sqlite:///aap_bridge.db")

    def _create_job(self, job_type: str, connection_id: str | None = None) -> str:
        job_id = str(uuid4())
        db = self.session_factory()
        try:
            job = Job(id=job_id, type=job_type, connection_id=connection_id, status="running")
            db.add(job)
            db.commit()
        finally:
            db.close()
        self.job_service.register_job(job_id)
        return job_id

    def _finish_job(
        self, job_id: str, status: str, error: str | None = None, metadata: dict | None = None
    ) -> None:
        db = self.session_factory()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = status
                job.finished_at = datetime.now(UTC)
                job.error = error
                if metadata:
                    job.job_metadata = metadata
                logs = self.job_service.get_logs_since(job_id, 0)
                job.output = logs
                db.commit()
        finally:
            db.close()

    @staticmethod
    def _job_logger() -> logging.Logger:
        return logging.getLogger("aap_migration")

    def _attach_log_handler(self, job_id: str) -> JobLogHandler:
        handler = JobLogHandler(self.job_service, job_id)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.addFilter(JobContextFilter(job_id))
        self._job_logger().addHandler(handler)
        return handler

    def _detach_log_handler(self, handler: JobLogHandler) -> None:
        self._job_logger().removeHandler(handler)

    def _snapshot_connection(self, conn: Connection) -> dict:
        return {
            "id": conn.id,
            "name": conn.name,
            "url": conn.url,
            "token": conn.token,
            "verify_ssl": conn.verify_ssl,
            "type": conn.type,
            "role": conn.role,
            "api_prefix": conn.api_prefix,
            "version": conn.version,
            "ping_status": conn.ping_status,
        }

    def _get_job(self, job_id: str) -> Job | None:
        db = self.session_factory()
        try:
            return db.query(Job).filter(Job.id == job_id).first()
        finally:
            db.close()

    @staticmethod
    def _summary_field_name(item: dict, field_name: str) -> str | None:
        summary_fields = item.get("summary_fields") or {}
        field_summary = summary_fields.get(field_name)
        if isinstance(field_summary, dict):
            return field_summary.get("name") or field_summary.get("username")
        return None

    @staticmethod
    def _summary_field_value(item: dict, field_name: str, value_name: str) -> str | None:
        summary_fields = item.get("summary_fields") or {}
        field_summary = summary_fields.get(field_name)
        if isinstance(field_summary, dict):
            value = field_summary.get(value_name)
            if isinstance(value, str):
                return value
        return None

    def _validate_preview_job(self, preview_job_id: str, source_id: str, destination_id: str) -> dict:
        preview_job = self._get_job(preview_job_id)
        if not preview_job or preview_job.type != "migration-preview":
            raise ValueError("Preview job not found")
        if preview_job.status != "completed" or not preview_job.job_metadata:
            raise ValueError("Preview job must complete successfully before starting a run")
        if preview_job.job_metadata.get("source_id") != source_id:
            raise ValueError("Preview job does not match the selected source connection")
        if preview_job.job_metadata.get("destination_id") != destination_id:
            raise ValueError("Preview job does not match the selected destination connection")
        return preview_job.job_metadata

    def start_prep(
        self,
        source: Connection,
        dest: Connection,
        *,
        force: bool = False,
    ) -> str:
        job_id = self._create_job("migration-prep", source.id)
        src_snap = self._snapshot_connection(source)
        dst_snap = self._snapshot_connection(dest)
        db_url = self._get_db_url()

        async def _run() -> None:
            try:
                from aap_migration.api.services.cli_workflows import run_migration_prep

                self.job_service.append_log(
                    job_id, f"Starting prep: {src_snap['name']} -> {dst_snap['name']}"
                )

                src_conn = Connection()
                for k, v in src_snap.items():
                    setattr(src_conn, k, v)
                dst_conn = Connection()
                for k, v in dst_snap.items():
                    setattr(dst_conn, k, v)

                result = await run_migration_prep(
                    src_conn,
                    dst_conn,
                    db_url,
                    force=force,
                    skip_if_exists=not force,
                    log=lambda message: self.job_service.append_log(job_id, message),
                )

                if result.status != "completed":
                    error_msg = result.message or "Prep failed"
                    self.job_service.append_log(job_id, error_msg)
                    self.job_service.mark_failed(job_id, error_msg)
                    self._finish_job(
                        job_id,
                        "failed",
                        error_msg,
                        metadata={"status": result.status, "skipped": result.skipped},
                    )
                else:
                    summary = "Prep skipped (schemas already exist)" if result.skipped else "Prep completed"
                    self.job_service.append_log(job_id, summary)
                    self.job_service.mark_completed(job_id)
                    self._finish_job(
                        job_id,
                        "completed",
                        metadata={"status": "completed", "skipped": result.skipped},
                    )
            except asyncio.CancelledError:
                self.job_service.append_log(job_id, "Prep cancelled")
                self.job_service.mark_cancelled(job_id)
                self._finish_job(job_id, "cancelled")
            except Exception as e:
                self.job_service.append_log(job_id, f"Prep failed: {e}")
                self.job_service.mark_failed(job_id, str(e))
                self._finish_job(job_id, "failed", str(e))

        task = asyncio.run_coroutine_threadsafe(_run(), self.loop)
        self.job_service.register_task(job_id, task)
        return job_id

    def start_preview(self, source: Connection, dest: Connection) -> str:
        job_id = self._create_job("migration-preview", source.id)
        src_snap = self._snapshot_connection(source)
        dst_snap = self._snapshot_connection(dest)

        async def _run() -> None:
            handler = self._attach_log_handler(job_id)
            context_token = ACTIVE_JOB_ID.set(job_id)
            try:
                from aap_migration.api.models import Connection as ConnModel
                from aap_migration.api.services.cli_workflows import run_migration_preview

                src_conn = ConnModel()
                for k, v in src_snap.items():
                    setattr(src_conn, k, v)
                dst_conn = ConnModel()
                for k, v in dst_snap.items():
                    setattr(dst_conn, k, v)

                self.job_service.append_log(
                    job_id, f"Starting migration preview: {src_snap['name']} -> {dst_snap['name']}"
                )

                result = await run_migration_preview(
                    src_conn,
                    dst_conn,
                    self._get_db_url(),
                    log=lambda message: self.job_service.append_log(job_id, message),
                )

                preview_data = {
                    "source_id": src_snap["id"],
                    "destination_id": dst_snap["id"],
                    "resources": result.resources,
                    "resource_summaries": result.resource_summaries,
                    "warnings": result.warnings,
                    "host_counts": result.host_counts,
                    "group_counts": result.group_counts,
                }
                self.job_service.mark_completed(job_id)
                self._finish_job(job_id, "completed", metadata=preview_data)
            except asyncio.CancelledError:
                self.job_service.append_log(job_id, "Preview cancelled")
                self.job_service.mark_cancelled(job_id)
                self._finish_job(job_id, "cancelled")
            except Exception as e:
                self.job_service.append_log(job_id, f"ERROR: {e}")
                self.job_service.mark_failed(job_id, str(e))
                self._finish_job(job_id, "failed", str(e))
            finally:
                ACTIVE_JOB_ID.reset(context_token)
                self._detach_log_handler(handler)

        task = asyncio.run_coroutine_threadsafe(_run(), self.loop)
        self.job_service.register_task(job_id, task)
        return job_id

    def get_preview(self, job_id: str) -> MigrationPreviewResponse | None:
        db = self.session_factory()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job or job.type != "migration-preview" or not job.job_metadata:
                return None
            return MigrationPreviewResponse(**job.job_metadata)
        finally:
            db.close()

    def _start_cli_pair_job(
        self,
        job_type: str,
        source: Connection,
        dest: Connection,
        *,
        label: str,
        runner,
        runner_kwargs: dict | None = None,
    ) -> str:
        job_id = self._create_job(job_type, source.id)
        src_snap = self._snapshot_connection(source)
        dst_snap = self._snapshot_connection(dest)
        db_url = self._get_db_url()
        kwargs = runner_kwargs or {}

        async def _run() -> None:
            handler = self._attach_log_handler(job_id)
            context_token = ACTIVE_JOB_ID.set(job_id)
            try:
                src_conn = Connection()
                for k, v in src_snap.items():
                    setattr(src_conn, k, v)
                dst_conn = Connection()
                for k, v in dst_snap.items():
                    setattr(dst_conn, k, v)

                self.job_service.append_log(
                    job_id, f"{label}: {src_snap['name']} -> {dst_snap['name']}"
                )
                result = await runner(
                    src_conn,
                    dst_conn,
                    db_url,
                    log=lambda message: self.job_service.append_log(job_id, message),
                    **kwargs,
                )
                status = getattr(result, "status", "completed")
                message = getattr(result, "message", "")
                if status != "completed":
                    error_msg = message or f"{label} failed"
                    self.job_service.append_log(job_id, error_msg)
                    self.job_service.mark_failed(job_id, error_msg)
                    self._finish_job(job_id, "failed", error_msg)
                else:
                    self.job_service.append_log(job_id, f"{label} completed successfully")
                    self.job_service.mark_completed(job_id)
                    self._finish_job(job_id, "completed")
            except asyncio.CancelledError:
                self.job_service.append_log(job_id, f"{label} cancelled")
                self.job_service.mark_cancelled(job_id)
                self._finish_job(job_id, "cancelled")
            except Exception as e:
                self.job_service.append_log(job_id, f"{label} failed: {e}")
                self.job_service.mark_failed(job_id, str(e))
                self._finish_job(job_id, "failed", str(e))
            finally:
                ACTIVE_JOB_ID.reset(context_token)
                self._detach_log_handler(handler)

        task = asyncio.run_coroutine_threadsafe(_run(), self.loop)
        self.job_service.register_task(job_id, task)
        return job_id

    def start_cleanup(self, source: Connection, dest: Connection) -> str:
        from aap_migration.api.services.cli_workflows import run_migration_cleanup

        async def _runner(_source, dest_conn, db_url, log=None):
            from aap_migration.api.services.cli_workflows import PhasedMigrationResult

            result = await run_migration_cleanup(dest_conn, db_url, log=log)
            if result.errors:
                return PhasedMigrationResult(
                    status="failed",
                    message=f"Cleanup completed with {result.errors} errors",
                )
            return PhasedMigrationResult(status="completed")

        return self._start_cli_pair_job(
            "cleanup",
            source,
            dest,
            label="Cleanup",
            runner=_runner,
        )

    def start_export(
        self,
        source: Connection,
        dest: Connection,
        *,
        force: bool = False,
        resume: bool = False,
    ) -> str:
        from aap_migration.api.services.cli_workflows import run_migration_export

        return self._start_cli_pair_job(
            "migration-export",
            source,
            dest,
            label="Export (all)",
            runner=run_migration_export,
            runner_kwargs={"force": force, "resume": resume},
        )

    def start_transform(
        self,
        source: Connection,
        dest: Connection,
        *,
        force: bool = False,
    ) -> str:
        from aap_migration.api.services.cli_workflows import run_migration_transform

        return self._start_cli_pair_job(
            "migration-transform",
            source,
            dest,
            label="Transform (all)",
            runner=run_migration_transform,
            runner_kwargs={"force": force},
        )

    def start_import(
        self,
        source: Connection,
        dest: Connection,
        *,
        phase: str,
        force: bool = False,
        resume: bool = False,
    ) -> str:
        from aap_migration.api.services.cli_workflows import run_migration_import

        phase_label = (
            "Import Phase 1 (Base Resources)"
            if phase == "phase1"
            else "Import Phase 2 (Patch Projects + Automation)"
        )
        return self._start_cli_pair_job(
            "migration-import",
            source,
            dest,
            label=phase_label,
            runner=run_migration_import,
            runner_kwargs={"phase": phase, "force": force, "resume": resume},
        )

    def start_run(
        self,
        source: Connection,
        dest: Connection,
        preview_job_id: str,
    ) -> str:
        self._validate_preview_job(preview_job_id, source.id, dest.id)
        job_id = self._create_job("migration-run", source.id)
        src_snap = self._snapshot_connection(source)
        dst_snap = self._snapshot_connection(dest)
        db_url = self._get_db_url()

        async def _run() -> None:
            handler = self._attach_log_handler(job_id)
            context_token = ACTIVE_JOB_ID.set(job_id)
            try:
                from aap_migration.api.services.cli_workflows import run_phased_migration

                self.job_service.append_log(
                    job_id, f"Starting migration: {src_snap['name']} -> {dst_snap['name']}"
                )

                src_conn = Connection()
                for k, v in src_snap.items():
                    setattr(src_conn, k, v)
                dst_conn = Connection()
                for k, v in dst_snap.items():
                    setattr(dst_conn, k, v)

                self.job_service.append_log(
                    job_id,
                    "Running phased migration (prep if needed → export → transform → import)...",
                )
                result = await run_phased_migration(
                    src_conn,
                    dst_conn,
                    db_url,
                    log=lambda message: self.job_service.append_log(job_id, message),
                )

                if result.status != "completed":
                    error_msg = result.message or "Phased migration failed"
                    self.job_service.append_log(job_id, error_msg)
                    self.job_service.mark_failed(job_id, error_msg)
                    self._finish_job(job_id, "failed", error_msg, metadata={"status": result.status})
                else:
                    self.job_service.append_log(job_id, "Migration completed successfully")
                    self.job_service.mark_completed(job_id)
                    self._finish_job(job_id, "completed", metadata={"status": "completed"})
            except asyncio.CancelledError:
                self.job_service.append_log(job_id, "Migration cancelled")
                self.job_service.mark_cancelled(job_id)
                self._finish_job(job_id, "cancelled")
            except Exception as e:
                self.job_service.append_log(job_id, f"Migration failed: {e}")
                self.job_service.mark_failed(job_id, str(e))
                self._finish_job(job_id, "failed", str(e))
            finally:
                ACTIVE_JOB_ID.reset(context_token)
                self._detach_log_handler(handler)

        task = asyncio.run_coroutine_threadsafe(_run(), self.loop)
        self.job_service.register_task(job_id, task)
        return job_id
