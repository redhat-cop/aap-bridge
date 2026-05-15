import asyncio
import contextvars
import logging
import time
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from aap_migration.api.models import Connection, Job
from aap_migration.api.schemas import MigrationPreviewResponse
from aap_migration.api.services.job_service import JobService
from aap_migration.config import normalized_credential_skip_names
from aap_migration.resources import (
    ORGANIZATION_SCOPED_RESOURCES,
    PARENT_SCOPED_RESOURCES,
    normalize_resource_type,
)

PREVIEW_RESOURCE_TYPES = [
    "organizations",
    "teams",
    "users",
    "credential_types",
    "credentials",
    "projects",
    "inventories",
    "hosts",
    "groups",
    "job_templates",
    "workflow_job_templates",
    "schedules",
]
PREVIEW_DETAIL_LIMIT = 200
PREVIEW_TRUNCATE_TYPES = {"hosts", "groups"}

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

    def _bar(self, done: int, total: int, width: int = 20) -> str:
        if total <= 0:
            return "█" * width
        filled = int(width * min(done, total) / total)
        return "█" * filled + "░" * (width - filled)

    def _rate(self) -> str:
        elapsed = time.time() - self._phase_start if self._phase_start else 0
        total = self._created + self._skipped + self._failed
        if elapsed > 0 and total > 0:
            return f"{total / elapsed:.1f}/s"
        return "--/s"

    def _elapsed(self) -> str:
        elapsed = time.time() - self._phase_start if self._phase_start else 0
        if elapsed < 60:
            return f"{elapsed:.0f}s"
        return f"{int(elapsed // 60)}m{int(elapsed % 60)}s"

    def _emit_progress(self, force: bool = False) -> None:
        total = self._created + self._skipped + self._failed
        if not force and total - self._last_emitted < 10:
            return
        self._last_emitted = total
        bar = self._bar(total, max(total, self._exported) if self._exported else total)
        self._log(
            f"  {bar} {total:>5} | "
            f"OK:{self._created} Skip:{self._skipped} Err:{self._failed} "
            f"| {self._rate()} {self._elapsed()}"
        )

    def _finish_phase(self) -> None:
        total = self._created + self._skipped + self._failed
        if total == 0 and self._exported == 0:
            return
        self._total_created += self._created
        self._total_skipped += self._skipped
        self._total_failed += self._failed
        status = "✓" if self._failed == 0 else "⚠"
        self._log(
            f"  {status} Done: {self._created} created, "
            f"{self._skipped} skipped, {self._failed} failed "
            f"({self._elapsed()})"
        )
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
            self._emit_progress(force=True)
            self._finish_phase()
            return

        if "phase_failed" in msg:
            self._emit_progress(force=True)
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
            if exported_str:
                self._exported = int(exported_str)
                if self._exported > 0:
                    self._log(f"  Exported {self._exported} resources")
            return

        # --- Import progress ---
        if "resource_import_failed" in msg:
            self._failed += 1
            name = self._extract("source_name=", msg) or self._extract("source_id=", msg)
            err = self._extract("error=", msg)[:80] if "error=" in msg else ""
            self._log(f"  ✗ Failed: {name} — {err}")
            self._emit_progress()
            return

        if "resource_skipped" in msg or "resources_skipped_summary" in msg:
            if "skipped_count=" in msg:
                cnt = int(self._extract("skipped_count=", msg) or "1")
                self._skipped += cnt
            else:
                self._skipped += 1
            self._emit_progress()
            return

        if "resource_created" in msg:
            self._created += 1
            self._emit_progress()
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
        )
        for n in noisy:
            if n in msg:
                return

        # --- Show warnings/errors ---
        if record.levelno >= logging.WARNING:
            clean = msg.split("version=")[0].strip() if "version=" in msg else msg
            if len(clean) > 200:
                clean = clean[:200] + "..."
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
            "api_prefix": conn.api_prefix,
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

    def _resource_identifier(self, resource_type: str, item: dict) -> str:
        username = item.get("username")
        if resource_type == "users" and isinstance(username, str) and username:
            return username
        name = item.get("name")
        if isinstance(name, str) and name:
            return name
        if isinstance(username, str) and username:
            return username
        return f"id-{item.get('id', '?')}"

    def _preview_match_key(self, resource_type: str, item: dict) -> str | tuple[str, str]:
        canonical_type = normalize_resource_type(resource_type)
        if canonical_type == "credentials":
            return f"credential:{item.get('id', '?')}"
        identifier = self._resource_identifier(resource_type, item)
        if canonical_type in ORGANIZATION_SCOPED_RESOURCES:
            org_name = self._summary_field_name(item, "organization")
            if org_name:
                return (identifier, org_name)
        if canonical_type in PARENT_SCOPED_RESOURCES:
            parent_field = PARENT_SCOPED_RESOURCES[canonical_type]
            parent_name = self._summary_field_name(item, parent_field)
            if parent_name:
                if parent_field == "unified_job_template":
                    parent_type = (
                        item.get("_ujt_resource_type")
                        or self._summary_field_value(item, parent_field, "unified_job_type")
                        or parent_field
                    )
                    return (identifier, f"{parent_type}:{parent_name}")
                return (identifier, parent_name)
        return identifier

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

    def start_preview(self, source: Connection, dest: Connection) -> str:
        job_id = self._create_job("migration-preview", source.id)
        src_snap = self._snapshot_connection(source)
        dst_snap = self._snapshot_connection(dest)

        async def _run() -> None:
            handler = self._attach_log_handler(job_id)
            context_token = ACTIVE_JOB_ID.set(job_id)
            try:
                from aap_migration.api.models import Connection as ConnModel
                from aap_migration.api.services.engine_adapter import load_runtime_config
                from aap_migration.api.services.platform_adapter import PlatformAdapter

                src_conn = ConnModel()
                for k, v in src_snap.items():
                    setattr(src_conn, k, v)
                dst_conn = ConnModel()
                for k, v in dst_snap.items():
                    setattr(dst_conn, k, v)

                src_adapter = PlatformAdapter(src_conn)
                dst_adapter = PlatformAdapter(dst_conn)
                runtime_config = load_runtime_config(src_conn, dst_conn, self._get_db_url())
                skip_credential_names = normalized_credential_skip_names(
                    runtime_config.export.skip_credential_names
                )

                self.job_service.append_log(
                    job_id, f"Starting migration preview: {src_snap['name']} -> {dst_snap['name']}"
                )

                resources: dict[str, list[dict]] = {}
                resource_summaries: dict[str, dict] = {}
                host_counts: dict[str, int] = {}
                group_counts: dict[str, int] = {}
                warnings: list[str] = []

                for rt in PREVIEW_RESOURCE_TYPES:
                    canonical_type = normalize_resource_type(rt)
                    self.job_service.append_log(job_id, f"Fetching {rt} from source...")
                    src_items = await asyncio.to_thread(src_adapter.fetch_all, rt)
                    if not src_items:
                        continue
                    if rt == "credentials" and skip_credential_names:
                        original_count = len(src_items)
                        src_items = [
                            item
                            for item in src_items
                            if str(item.get("name", "")).strip().casefold() not in skip_credential_names
                        ]
                        skipped_by_policy = original_count - len(src_items)
                        if skipped_by_policy:
                            warnings.append(
                                f"Excluded {skipped_by_policy} credentials based on export.skip_credential_names."
                            )
                    if not src_items:
                        continue

                    self.job_service.append_log(job_id, f"  Found {len(src_items)} {rt} on source")
                    self.job_service.append_log(job_id, f"Fetching {rt} from destination...")
                    dst_items = await asyncio.to_thread(dst_adapter.fetch_all, rt)
                    dst_keys = (
                        set()
                        if canonical_type == "credentials"
                        else {self._preview_match_key(rt, item) for item in dst_items}
                    )
                    self.job_service.append_log(
                        job_id, f"  Found {len(dst_items)} {rt} on destination"
                    )

                    display_resources: list[dict] = []
                    total_count = 0
                    create_count = 0
                    should_truncate = rt in PREVIEW_TRUNCATE_TYPES
                    for item in src_items:
                        name = self._resource_identifier(rt, item)
                        action = (
                            "create"
                            if canonical_type == "credentials"
                            else "skip_exists"
                            if self._preview_match_key(rt, item) in dst_keys
                            else "create"
                        )
                        total_count += 1
                        if action == "create":
                            create_count += 1
                        if not should_truncate or len(display_resources) < PREVIEW_DETAIL_LIMIT:
                            display_resources.append(
                                {
                                    "source_id": item.get("id", 0),
                                    "name": name,
                                    "type": rt,
                                    "action": action,
                                }
                            )

                    if total_count:
                        summary = {
                            "total": total_count,
                            "create": create_count,
                            "skip_exists": total_count - create_count,
                            "displayed": len(display_resources),
                            "truncated": should_truncate and total_count > PREVIEW_DETAIL_LIMIT,
                        }
                        if summary["truncated"]:
                            warnings.append(
                                f"{rt} preview is truncated to the first {PREVIEW_DETAIL_LIMIT} rows."
                            )
                        resources[rt] = display_resources
                        resource_summaries[rt] = summary

                    if rt == "inventories":
                        for item in src_items:
                            inv_name = item.get("name", "")
                            host_counts[inv_name] = item.get("total_hosts", 0)
                            group_counts[inv_name] = item.get("total_groups", 0)

                total_create = sum(
                    1 for items in resources.values() for i in items if i["action"] == "create"
                )
                total_skip = sum(
                    1 for items in resources.values() for i in items if i["action"] != "create"
                )
                self.job_service.append_log(
                    job_id, f"Preview complete: {total_create} to create, {total_skip} to skip"
                )

                preview_data = {
                    "source_id": src_snap["id"],
                    "destination_id": dst_snap["id"],
                    "resources": resources,
                    "resource_summaries": resource_summaries,
                    "warnings": warnings,
                    "host_counts": host_counts,
                    "group_counts": group_counts,
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
                from aap_migration.api.services.engine_adapter import build_migration_config
                from aap_migration.client.aap_source_client import AAPSourceClient
                from aap_migration.client.aap_target_client import AAPTargetClient
                from aap_migration.migration.coordinator import MigrationCoordinator
                from aap_migration.migration.state import MigrationState

                self.job_service.append_log(
                    job_id, f"Starting migration: {src_snap['name']} -> {dst_snap['name']}"
                )

                src_conn = Connection()
                for k, v in src_snap.items():
                    setattr(src_conn, k, v)
                dst_conn = Connection()
                for k, v in dst_snap.items():
                    setattr(dst_conn, k, v)

                config = build_migration_config(src_conn, dst_conn, db_url)

                self.job_service.append_log(job_id, "Initializing clients...")
                source_client = AAPSourceClient(config.source)
                target_client = AAPTargetClient(config.target)

                self.job_service.append_log(job_id, "Initializing migration state...")
                state = MigrationState(config.state)

                coordinator = MigrationCoordinator(
                    config=config,
                    source_client=source_client,
                    target_client=target_client,
                    state=state,
                    enable_progress=False,
                    show_stats=False,
                )

                self.job_service.append_log(job_id, "Running migration...")
                summary = await coordinator.migrate_all(
                    generate_report=True,
                    report_dir="./reports",
                )

                status_msg = summary.get("status", "unknown")
                exported = summary.get("total_resources_exported", 0)
                imported = summary.get("total_resources_imported", 0)
                failed = summary.get("total_resources_failed", 0)
                skipped = summary.get("total_resources_skipped", 0)

                self.job_service.append_log(
                    job_id,
                    f"Migration {status_msg}: exported={exported} imported={imported} "
                    f"failed={failed} skipped={skipped}",
                )

                if status_msg == "completed_with_errors" or failed:
                    error_msg = f"Migration completed with {failed} failed resources"
                    self.job_service.mark_failed(job_id, error_msg)
                    self._finish_job(job_id, "failed", error_msg, metadata=summary)
                else:
                    self.job_service.mark_completed(job_id)
                    self._finish_job(job_id, "completed", metadata=summary)
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
