from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aap_migration.migration.models import Base


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    token: Mapped[str | None] = mapped_column(Text, nullable=True)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    api_prefix: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ping_status: Mapped[str] = mapped_column(String(20), default="unknown")
    ping_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_status: Mapped[str] = mapped_column(String(20), default="unknown")
    auth_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="connection")

    __table_args__ = (
        Index("idx_connections_role", "role"),
        Index("idx_connections_type", "type"),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    connection_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("connections.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    output: Mapped[list] = mapped_column(JSON, default=list)
    job_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    connection: Mapped[Connection | None] = relationship("Connection", back_populates="jobs")

    __table_args__ = (
        Index("idx_jobs_status", "status"),
        Index("idx_jobs_type", "type"),
        Index("idx_jobs_started_at", "started_at"),
    )
