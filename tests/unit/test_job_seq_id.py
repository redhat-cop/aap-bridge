from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from aap_migration.api.db_schema import allocate_job_seq_id, ensure_jobs_seq_id_column
from aap_migration.api.models import Base, Job


def _session() -> tuple[Session, sessionmaker[Session]]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return factory(), factory


def test_allocate_job_seq_id_starts_at_one() -> None:
    db, _ = _session()
    try:
        assert allocate_job_seq_id(db) == 1
    finally:
        db.close()


def test_allocate_job_seq_id_skips_null_legacy_rows() -> None:
    db, factory = _session()
    try:
        db.add(Job(id="legacy-1", type="cleanup", status="completed"))
        db.commit()

        db2 = factory()
        try:
            assert allocate_job_seq_id(db2) == 1
        finally:
            db2.close()
    finally:
        db.close()


def test_allocate_job_seq_id_increments_from_max() -> None:
    db, factory = _session()
    try:
        db.add(Job(id="job-1", seq_id=3, type="cleanup", status="completed"))
        db.add(Job(id="job-2", type="cleanup", status="completed"))
        db.commit()

        db2 = factory()
        try:
            assert allocate_job_seq_id(db2) == 4
        finally:
            db2.close()
    finally:
        db.close()


def test_ensure_jobs_seq_id_column_adds_column_to_existing_table() -> None:
    from sqlalchemy import inspect

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE jobs (
                id VARCHAR(36) PRIMARY KEY,
                type VARCHAR(50) NOT NULL,
                connection_id VARCHAR(36),
                status VARCHAR(20) NOT NULL,
                started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME,
                error TEXT,
                output JSON,
                job_metadata JSON
            )
            """
        )

    ensure_jobs_seq_id_column(engine)

    columns = {col["name"] for col in inspect(engine).get_columns("jobs")}
    assert "seq_id" in columns
