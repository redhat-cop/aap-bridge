"""Lightweight schema adjustments for existing API databases.

create_all() only creates missing tables; it does not add columns. These helpers
run at API startup so deployed databases pick up additive changes.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from aap_migration.api.models import Job


def ensure_jobs_seq_id_column(engine: Engine) -> None:
    """Add jobs.seq_id when missing. Existing rows keep NULL (no backfill)."""
    if "jobs" not in inspect(engine).get_table_names():
        return

    columns = {col["name"] for col in inspect(engine).get_columns("jobs")}
    if "seq_id" in columns:
        return

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE jobs ADD COLUMN seq_id INTEGER"))


def allocate_job_seq_id(db: Session) -> int:
    """Return the next display sequence number for a new job."""
    current = db.query(func.max(Job.seq_id)).scalar()
    return int(current or 0) + 1
