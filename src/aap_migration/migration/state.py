"""
Migration state management.

This module provides the MigrationState class for tracking and managing
the state of individual resources during migration from source AAP to target AAP.
"""

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, overload

from sqlalchemy import func

from aap_migration.client.exceptions import StateError
from aap_migration.config import StateConfig
from aap_migration.migration.database import get_session, init_database
from aap_migration.migration.models import (
    IDMapping,
    MigrationProgress,
)
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ExportRunContext:
    source_url: str
    source_version: str | None  # discovered AAP version, if available
    output_dir: str  # resolved absolute path
    resource_types: tuple[str, ...]  # sorted, for deterministic hashing
    filters: tuple[tuple[str, str], ...]  # sorted key-value pairs
    state_dsn_fingerprint: str  # SHA-256[:16] of the state DB DSN
    timestamp: str  # ISO-8601 creation time

    @staticmethod
    def hash_dsn(dsn: str) -> str:
        """Hash a DB connection string for safe storage and comparison."""
        import hashlib

        return hashlib.sha256(dsn.encode()).hexdigest()[:16]

    @property
    def run_fingerprint(self) -> str:
        """SHA-256 of identity fields (excludes timestamp)."""
        import hashlib

        identity = (
            f"{self.source_url}|{self.source_version}|{self.output_dir}"
            f"|{self.resource_types}|{self.filters}|{self.state_dsn_fingerprint}"
        )
        return hashlib.sha256(identity.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "source_version": self.source_version,
            "output_dir": self.output_dir,
            "resource_types": list(self.resource_types),
            "filters": dict(self.filters),
            "state_dsn_fingerprint": self.state_dsn_fingerprint,
            "timestamp": self.timestamp,
            "run_fingerprint": self.run_fingerprint,
        }


class MigrationState:
    """
    Manages migration state for tracking resource migration progress.

    This class provides thread-safe methods for tracking which resources
    have been migrated, managing ID mappings, and recording migration
    progress. It uses SQLAlchemy for database operations and supports
    both SQLite and PostgreSQL.

    Usage:
        with MigrationState(config, migration_id) as state:
            if not state.is_migrated("inventory", source_id=123):
                state.mark_in_progress("inventory", source_id=123, source_name="Test")
                # ... perform migration ...
                state.mark_completed("inventory", source_id=123, target_id=456)
    """

    def __init__(
        self,
        config: StateConfig,
        migration_id: str | None = None,
        migration_name: str | None = None,
    ):
        """
        Initialize migration state manager.

        Args:
            config: State configuration
            migration_id: Unique identifier for this migration run (generates UUID if None)
            migration_name: Human-readable name for this migration

        Raises:
            StateError: If initialization fails
        """
        self.config = config
        self.migration_id = migration_id or str(uuid.uuid4())
        self.migration_name = migration_name
        self._lock = threading.RLock()  # Reentrant lock for thread safety

        # Initialize database
        try:
            # Support both full database URLs and file paths
            if config.db_path.startswith(("postgresql://", "sqlite://", "mysql://")):
                # Already a full database URL, use as-is
                self.database_url = config.db_path
            else:
                # Treat as SQLite file path
                self.database_url = f"sqlite:///{config.db_path}"

            init_database(
                self.database_url,
                pool_size=config.db_pool_size,
                max_overflow=config.db_max_overflow,
                pool_timeout=config.db_pool_timeout,
                pool_recycle=config.db_pool_recycle,
            )
            logger.info(
                "Migration state initialized",
                migration_id=self.migration_id,
                database_path=config.db_path,
            )
        except Exception as e:
            logger.error("Failed to initialize migration state", error=str(e))
            raise StateError(f"Failed to initialize migration state: {e}") from e

    def __enter__(self) -> "MigrationState":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        # No cleanup needed as sessions are managed per operation

    @overload
    def _normalize(self, resource_type: str) -> str: ...

    @overload
    def _normalize(self, resource_type: None) -> None: ...

    def _normalize(self, resource_type: str | None) -> str | None:
        """Normalize resource type using canonical naming policy. (REQ-005)"""
        if resource_type is None:
            return None
        from aap_migration.resources import normalize_resource_type

        return normalize_resource_type(resource_type)

    def is_migrated(
        self,
        resource_type: str,
        source_id: int,
    ) -> bool:
        """
        Check if a resource has already been migrated.

        Args:
            resource_type: Type of resource (e.g., 'inventory', 'host')
            source_id: Source system resource ID

        Returns:
            True if resource is completed or in_progress, False otherwise
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    progress = (
                        session.query(MigrationProgress)
                        .filter_by(resource_type=resource_type, source_id=source_id)
                        .first()
                    )

                    if progress is None:
                        return False

                    # Consider completed or in_progress as "migrated" to avoid duplicates
                    is_migrated = progress.status in ("completed", "in_progress")

                    logger.debug(
                        "Checked migration status",
                        resource_type=resource_type,
                        source_id=source_id,
                        status=progress.status if progress else "not_found",
                        is_migrated=is_migrated,
                    )

                    return is_migrated

            except Exception as e:
                logger.error(
                    "Failed to check migration status",
                    resource_type=resource_type,
                    source_id=source_id,
                    error=str(e),
                )
                raise StateError(f"Failed to check migration status: {e}") from e

    def has_mapping(
        self,
        resource_type: str,
        source_id: int,
    ) -> bool:
        """
        Check if an ID mapping exists for a resource (used for export resume).

        This checks the IDMapping table, not MigrationProgress. Used by exporters
        to skip already-exported resources during resume.

        Args:
            resource_type: Type of resource (e.g., 'inventory', 'host')
            source_id: Source system resource ID

        Returns:
            True if mapping exists, False otherwise
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    mapping = (
                        session.query(IDMapping)
                        .filter_by(resource_type=resource_type, source_id=source_id)
                        .first()
                    )

                    has_mapping = mapping is not None

                    logger.debug(
                        "Checked ID mapping existence",
                        resource_type=resource_type,
                        source_id=source_id,
                        has_mapping=has_mapping,
                    )

                    return has_mapping

            except Exception as e:
                logger.error(
                    "Failed to check ID mapping",
                    resource_type=resource_type,
                    source_id=source_id,
                    error=str(e),
                )
                raise StateError(f"Failed to check ID mapping: {e}") from e

    def get_all_source_ids(self, resource_type: str) -> list[int]:
        """
        Get all source IDs for a resource type in a single query.

        Used for efficient export resume - load all mappings into memory
        instead of querying per-resource (eliminates N+1 query problem).

        Args:
            resource_type: Type of resource (e.g., 'hosts', 'inventories')

        Returns:
            List of source IDs that have been mapped
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    # Single query to get all source IDs for this resource type
                    result = (
                        session.query(IDMapping.source_id)
                        .filter_by(resource_type=resource_type)
                        .all()
                    )

                    source_ids = [row[0] for row in result]

                    logger.info(
                        "Fetched all source IDs for resource type",
                        resource_type=resource_type,
                        count=len(source_ids),
                    )

                    return source_ids

            except Exception as e:
                logger.error(
                    "Failed to fetch source IDs",
                    resource_type=resource_type,
                    error=str(e),
                )
                raise StateError(f"Failed to fetch source IDs: {e}") from e

    def get_max_exported_id(self, resource_type: str) -> int | None:
        """
        Get the maximum source_id that has been exported for a resource type.

        Used for true checkpoint resume - allows skipping API calls entirely
        by filtering with ?id__gt=max_id&order_by=id

        Args:
            resource_type: Type of resource (e.g., 'hosts', 'inventories')

        Returns:
            Maximum source_id or None if no resources exported yet
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    # Single query to get max source_id
                    result = (
                        session.query(func.max(IDMapping.source_id))
                        .filter_by(resource_type=resource_type)
                        .scalar()
                    )

                    logger.info(
                        "Fetched max exported ID for resource type",
                        resource_type=resource_type,
                        max_id=result,
                    )

                    return result

            except Exception as e:
                logger.error(
                    "Failed to fetch max exported ID",
                    resource_type=resource_type,
                    error=str(e),
                )
                raise StateError(f"Failed to fetch max exported ID: {e}") from e

    def get_imported_source_ids(self, resource_type: str) -> set[int]:
        """
        Get all source_ids that have been successfully imported (target_id IS NOT NULL).

        Used for import resume - skip resources that already exist in target.

        Args:
            resource_type: Type of resource (e.g., 'hosts', 'inventories')

        Returns:
            Set of source_ids that have target_id populated
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    result = (
                        session.query(IDMapping.source_id)
                        .filter(
                            IDMapping.resource_type == resource_type,
                            IDMapping.target_id.isnot(None),  # Only successfully imported
                        )
                        .all()
                    )

                    source_ids = {row[0] for row in result}

                    logger.info(
                        "Fetched imported source IDs",
                        resource_type=resource_type,
                        count=len(source_ids),
                    )

                    return source_ids

            except Exception as e:
                logger.error(
                    "Failed to fetch imported source IDs",
                    resource_type=resource_type,
                    error=str(e),
                )
                raise StateError(f"Failed to fetch imported source IDs: {e}") from e

    def get_import_stats(self, resource_type: str) -> dict:
        """
        Get import progress statistics for a resource type.

        Args:
            resource_type: Type of resource (e.g., 'hosts', 'inventories')

        Returns:
            Dictionary with import statistics:
            {
                'total_exported': int,
                'total_imported': int,
                'pending': int,
                'percent_complete': float
            }
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    # Total exported (all mappings for this resource type)
                    total = (
                        session.query(func.count(IDMapping.id))
                        .filter(IDMapping.resource_type == resource_type)
                        .scalar()
                    )

                    # Total imported (mappings with target_id set)
                    imported = (
                        session.query(func.count(IDMapping.id))
                        .filter(
                            IDMapping.resource_type == resource_type,
                            IDMapping.target_id.isnot(None),
                        )
                        .scalar()
                    )

                    pending = total - imported
                    percent_complete = (imported / total * 100) if total > 0 else 0

                    stats = {
                        "total_exported": total,
                        "total_imported": imported,
                        "pending": pending,
                        "percent_complete": percent_complete,
                    }

                    logger.info(
                        "Fetched import stats",
                        resource_type=resource_type,
                        stats=stats,
                    )

                    return stats

            except Exception as e:
                logger.error(
                    "Failed to fetch import stats",
                    resource_type=resource_type,
                    error=str(e),
                )
                raise StateError(f"Failed to fetch import stats: {e}") from e

    def detect_partial_import(self) -> dict[str, dict]:
        """
        Detect if there are partial imports (some resources exported but not imported).

        Returns:
            Dict of resource types with partial import stats:
            {
                'inventories': {'total_exported': 5393, 'total_imported': 3000, 'pending': 2393, 'percent_complete': 55.6},
                'hosts': {'total_exported': 54259, 'total_imported': 0, 'pending': 54259, 'percent_complete': 0.0}
            }
        """
        partial_imports = {}

        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    # Get all resource types with mappings
                    resource_types = session.query(IDMapping.resource_type).distinct().all()

                    for (rtype,) in resource_types:
                        stats = self.get_import_stats(rtype)
                        if stats["pending"] > 0:
                            partial_imports[rtype] = stats

                logger.info(
                    "Detected partial imports",
                    partial_imports=partial_imports,
                )

                return partial_imports

            except Exception as e:
                logger.error(
                    "Failed to detect partial imports",
                    error=str(e),
                )
                raise StateError(f"Failed to detect partial imports: {e}") from e

    def update_mapping_target_id(
        self,
        resource_type: str,
        source_id: int,
        target_id: int,
        target_name: str | None = None,
    ) -> None:
        """
        Update the target_id for an existing ID mapping (used during import).

        Args:
            resource_type: Type of resource
            source_id: Source system resource ID
            target_id: Target system resource ID
            target_name: Optional name in target system

        Raises:
            StateError: If operation fails or mapping not found
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    mapping = (
                        session.query(IDMapping)
                        .filter_by(resource_type=resource_type, source_id=source_id)
                        .first()
                    )

                    if mapping is None:
                        raise StateError(
                            f"Cannot update mapping: Not found "
                            f"(type={resource_type}, source_id={source_id})"
                        )

                    mapping.target_id = target_id
                    if target_name:
                        mapping.target_name = target_name

                    session.commit()

                    logger.debug(
                        "Updated mapping target_id",
                        resource_type=resource_type,
                        source_id=source_id,
                        target_id=target_id,
                    )

            except Exception as e:
                logger.error(
                    "Failed to update mapping target_id",
                    resource_type=resource_type,
                    source_id=source_id,
                    target_id=target_id,
                    error=str(e),
                )
                raise StateError(f"Failed to update mapping target_id: {e}") from e

    def get_status(
        self,
        resource_type: str,
        source_id: int,
    ) -> str | None:
        """
        Get the current migration status of a resource.

        Args:
            resource_type: Type of resource
            source_id: Source system resource ID

        Returns:
            Status string ('pending', 'in_progress', 'completed', 'failed', 'skipped')
            or None if resource not found
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    progress = (
                        session.query(MigrationProgress)
                        .filter_by(resource_type=resource_type, source_id=source_id)
                        .first()
                    )

                    return progress.status if progress else None

            except Exception as e:
                logger.error(
                    "Failed to get migration status",
                    resource_type=resource_type,
                    source_id=source_id,
                    error=str(e),
                )
                raise StateError(f"Failed to get migration status: {e}") from e

    def mark_in_progress(
        self,
        resource_type: str,
        source_id: int,
        source_name: str,
        phase: str = "import",
    ) -> None:
        """
        Mark a resource migration as in progress.

        Args:
            resource_type: Type of resource
            source_id: Source system resource ID
            source_name: Name of resource in source system
            phase: Migration phase (default: 'import')

        Raises:
            StateError: If operation fails
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    # Check if record exists
                    progress = (
                        session.query(MigrationProgress)
                        .filter_by(resource_type=resource_type, source_id=source_id)
                        .first()
                    )

                    if progress is None:
                        # Create new record
                        progress = MigrationProgress(
                            resource_type=resource_type,
                            source_id=source_id,
                            source_name=source_name,
                            status="in_progress",
                            phase=phase,
                            started_at=datetime.now(UTC),
                        )
                        session.add(progress)
                    else:
                        # Update existing record
                        progress.status = "in_progress"
                        progress.phase = phase
                        progress.started_at = datetime.now(UTC)

                    session.commit()

                    logger.info(
                        "Marked resource as in_progress",
                        resource_type=resource_type,
                        source_id=source_id,
                        source_name=source_name,
                        phase=phase,
                    )

            except Exception as e:
                logger.error(
                    "Failed to mark resource as in_progress",
                    resource_type=resource_type,
                    source_id=source_id,
                    error=str(e),
                )
                raise StateError(f"Failed to mark resource as in_progress: {e}") from e

    def mark_completed(
        self,
        resource_type: str,
        source_id: int,
        target_id: int,
        target_name: str | None = None,
        source_name: str | None = None,
    ) -> None:
        """
        Mark a resource migration as completed.

        Args:
            resource_type: Type of resource
            source_id: Source system resource ID
            target_id: Target system resource ID
            target_name: Name of resource in target system
            source_name: Name of resource in source system (required if record doesn't exist)

        Raises:
            StateError: If operation fails or resource not found (and source_name not provided)
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    progress = (
                        session.query(MigrationProgress)
                        .filter_by(resource_type=resource_type, source_id=source_id)
                        .first()
                    )

                    if progress is None:
                        logger.debug(
                            "progress_record_missing",
                            resource_type=resource_type,
                            source_id=source_id,
                            source_name=source_name,
                            target_id=target_id,
                        )
                        if source_name:
                            # Create completed record on the fly (seeding)
                            progress = MigrationProgress(
                                resource_type=resource_type,
                                source_id=source_id,
                                source_name=source_name,
                                target_id=target_id,
                                status="completed",
                                phase="transform",  # Assume transform phase for seeding
                                started_at=datetime.now(UTC),
                                completed_at=datetime.now(UTC),
                            )
                            session.add(progress)
                        else:
                            raise StateError(
                                f"Cannot mark as completed: Resource not found "
                                f"(type={resource_type}, source_id={source_id})"
                            )
                    else:
                        # Update progress
                        progress.status = "completed"
                        progress.target_id = target_id
                        progress.completed_at = datetime.now(UTC)

                    session.commit()

                    # Create ID mapping
                    self.save_id_mapping(
                        resource_type=resource_type,
                        source_id=source_id,
                        target_id=target_id,
                        source_name=progress.source_name,
                        target_name=target_name,
                        migration_progress_id=progress.id,
                    )

                    logger.info(
                        "Marked resource as completed",
                        resource_type=resource_type,
                        source_id=source_id,
                        target_id=target_id,
                    )

            except Exception as e:
                logger.error(
                    "Failed to mark resource as completed",
                    resource_type=resource_type,
                    source_id=source_id,
                    error=str(e),
                )
                raise StateError(f"Failed to mark resource as completed: {e}") from e

    def mark_failed(
        self,
        resource_type: str,
        source_id: int,
        error_message: str,
        increment_retry: bool = True,
    ) -> None:
        """
        Mark a resource migration as failed.

        Args:
            resource_type: Type of resource
            source_id: Source system resource ID
            error_message: Error message describing the failure
            increment_retry: Whether to increment retry counter

        Raises:
            StateError: If operation fails
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    progress = (
                        session.query(MigrationProgress)
                        .filter_by(resource_type=resource_type, source_id=source_id)
                        .first()
                    )

                    if progress is None:
                        logger.warning(
                            "Cannot mark as failed: resource not tracked "
                            "in progress table, skipping",
                            resource_type=resource_type,
                            source_id=source_id,
                            error_message=error_message,
                        )
                        return

                    # Update progress
                    progress.status = "failed"
                    progress.error_message = error_message
                    progress.completed_at = datetime.now(UTC)
                    if increment_retry:
                        progress.retry_count += 1

                    session.commit()

                    logger.warning(
                        "Marked resource as failed",
                        resource_type=resource_type,
                        source_id=source_id,
                        error_message=error_message,
                        retry_count=progress.retry_count,
                    )

            except Exception as e:
                logger.error(
                    "Failed to mark resource as failed",
                    resource_type=resource_type,
                    source_id=source_id,
                    error=str(e),
                )
                raise StateError(f"Failed to mark resource as failed: {e}") from e

    def mark_skipped(
        self,
        resource_type: str,
        source_id: int,
        reason: str,
    ) -> None:
        """
        Mark a resource as skipped (will not be migrated).

        Args:
            resource_type: Type of resource
            source_id: Source system resource ID
            reason: Reason for skipping

        Raises:
            StateError: If operation fails
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    progress = (
                        session.query(MigrationProgress)
                        .filter_by(resource_type=resource_type, source_id=source_id)
                        .first()
                    )

                    if progress is None:
                        logger.warning(
                            "Cannot mark as skipped: resource not tracked "
                            "in progress table, skipping",
                            resource_type=resource_type,
                            source_id=source_id,
                            reason=reason,
                        )
                        return

                    # Update progress
                    progress.status = "skipped"
                    progress.error_message = f"Skipped: {reason}"
                    progress.completed_at = datetime.now(UTC)

                    session.commit()

                    logger.info(
                        "Marked resource as skipped",
                        resource_type=resource_type,
                        source_id=source_id,
                        reason=reason,
                    )

            except Exception as e:
                logger.error(
                    "Failed to mark resource as skipped",
                    resource_type=resource_type,
                    source_id=source_id,
                    error=str(e),
                )
                raise StateError(f"Failed to mark resource as skipped: {e}") from e

    def save_id_mapping(
        self,
        resource_type: str,
        source_id: int,
        target_id: int,
        source_name: str | None = None,
        target_name: str | None = None,
        migration_progress_id: int | None = None,
        mapping_metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Save an ID mapping from source to target system.

        Args:
            resource_type: Type of resource
            source_id: Source system resource ID
            target_id: Target system resource ID
            source_name: Name in source system
            target_name: Name in target system
            migration_progress_id: Reference to migration progress record
            mapping_metadata: Additional metadata

        Raises:
            StateError: If operation fails
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    # Check if mapping already exists
                    existing = (
                        session.query(IDMapping)
                        .filter_by(resource_type=resource_type, source_id=source_id)
                        .first()
                    )

                    if existing:
                        # Update existing mapping
                        existing.target_id = target_id
                        if source_name:
                            existing.source_name = source_name
                        if target_name:
                            existing.target_name = target_name
                        if migration_progress_id:
                            existing.migration_progress_id = migration_progress_id
                        if mapping_metadata:
                            existing.mapping_metadata = mapping_metadata
                    else:
                        # Create new mapping
                        mapping = IDMapping(
                            resource_type=resource_type,
                            source_id=source_id,
                            target_id=target_id,
                            source_name=source_name,
                            target_name=target_name,
                            migration_progress_id=migration_progress_id,
                            mapping_metadata=mapping_metadata,
                        )
                        session.add(mapping)

                    session.commit()

                    logger.debug(
                        "Saved ID mapping",
                        resource_type=resource_type,
                        source_id=source_id,
                        target_id=target_id,
                    )

            except Exception as e:
                logger.error(
                    "Failed to save ID mapping",
                    resource_type=resource_type,
                    source_id=source_id,
                    target_id=target_id,
                    error=str(e),
                )
                raise StateError(f"Failed to save ID mapping: {e}") from e

    def get_mapped_id(
        self,
        resource_type: str,
        source_id: int,
    ) -> int | None:
        """
        Get the target ID for a source resource ID.

        Args:
            resource_type: Type of resource
            source_id: Source system resource ID

        Returns:
            Target ID if mapping exists, None otherwise
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    mapping = (
                        session.query(IDMapping)
                        .filter_by(resource_type=resource_type, source_id=source_id)
                        .first()
                    )

                    return mapping.target_id if mapping else None

            except Exception as e:
                logger.error(
                    "Failed to get mapped ID",
                    resource_type=resource_type,
                    source_id=source_id,
                    error=str(e),
                )
                raise StateError(f"Failed to get mapped ID: {e}") from e

    def get_progress_target_id(
        self,
        resource_type: str,
        source_id: int,
    ) -> int | None:
        """Get the target ID stored in MigrationProgress for a source resource.

        Unlike get_mapped_id() which reads IDMapping (reset between runs), this
        reads MigrationProgress which is never cleared, making it safe to call
        after reset_target_ids_for_source_ids() has nulled out IDMapping rows.

        Args:
            resource_type: Type of resource
            source_id: Source system resource ID

        Returns:
            Target ID recorded when the resource was last completed, or None
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    progress = (
                        session.query(MigrationProgress)
                        .filter_by(
                            resource_type=resource_type,
                            source_id=source_id,
                            status="completed",
                        )
                        .first()
                    )
                    return progress.target_id if progress else None

            except Exception as e:
                logger.error(
                    "failed_to_get_progress_target_id",
                    resource_type=resource_type,
                    source_id=source_id,
                    error=str(e),
                )
                raise StateError(f"Failed to get progress target ID: {e}") from e

    def get_mapped_id_by_name(
        self,
        resource_type: str,
        source_name: str,
    ) -> int | None:
        """
        Get the target ID for a resource by its source name.

        Useful when resolving references by name rather than source ID,
        such as mapping role definition names to target IDs.

        Args:
            resource_type: Type of resource
            source_name: Name in source system

        Returns:
            Target ID if mapping exists, None otherwise
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    mapping = (
                        session.query(IDMapping)
                        .filter_by(resource_type=resource_type, source_name=source_name)
                        .first()
                    )

                    return mapping.target_id if mapping else None

            except Exception as e:
                logger.error(
                    "Failed to get mapped ID by name",
                    resource_type=resource_type,
                    source_name=source_name,
                    error=str(e),
                )
                raise StateError(f"Failed to get mapped ID by name: {e}") from e

    def create_or_update_mapping(
        self,
        resource_type: str,
        source_id: int,
        target_id: int | None,
        source_name: str | None = None,
    ) -> None:
        """
        Create or update an ID mapping (used during export with target_id=None).

        Args:
            resource_type: Type of resource
            source_id: Source system resource ID
            target_id: Target system resource ID (can be None during export)
            source_name: Name in source system

        Raises:
            StateError: If operation fails
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    # Check if mapping already exists
                    existing = (
                        session.query(IDMapping)
                        .filter_by(resource_type=resource_type, source_id=source_id)
                        .first()
                    )

                    if existing:
                        # Update existing mapping
                        if target_id is not None:
                            existing.target_id = target_id
                        if source_name:
                            existing.source_name = source_name
                    else:
                        # Create new mapping
                        mapping = IDMapping(
                            resource_type=resource_type,
                            source_id=source_id,
                            target_id=target_id,
                            source_name=source_name,
                        )
                        session.add(mapping)

                    session.commit()

                    logger.debug(
                        "Created/updated ID mapping",
                        resource_type=resource_type,
                        source_id=source_id,
                        target_id=target_id,
                        source_name=source_name,
                    )

            except Exception as e:
                logger.error(
                    "Failed to create/update ID mapping",
                    resource_type=resource_type,
                    source_id=source_id,
                    error=str(e),
                )
                raise StateError(f"Failed to create/update ID mapping: {e}") from e

    def batch_create_mappings(
        self,
        mappings: list[dict],
        batch_size: int = 100,
    ) -> int:
        """
        Create or update multiple ID mappings in batches for better performance.

        This method reduces database commit overhead by batching multiple mappings
        into single transactions. Expected to be 50-100x faster than individual commits.

        Args:
            mappings: List of dicts with keys: resource_type, source_id, target_id, source_name
            batch_size: Number of mappings per commit (default: 100)

        Returns:
            Number of mappings processed

        Raises:
            StateError: If operation fails
        """
        if not mappings:
            return 0

        with self._lock:
            try:
                total_processed = 0

                with get_session(self.database_url) as session:
                    for i in range(0, len(mappings), batch_size):
                        batch = mappings[i : i + batch_size]

                        for mapping_data in batch:
                            # Check if mapping already exists
                            existing = (
                                session.query(IDMapping)
                                .filter_by(
                                    resource_type=mapping_data["resource_type"],
                                    source_id=mapping_data["source_id"],
                                )
                                .first()
                            )

                            if existing:
                                # Update existing mapping
                                if mapping_data.get("target_id") is not None:
                                    existing.target_id = mapping_data["target_id"]
                                if mapping_data.get("source_name"):
                                    existing.source_name = mapping_data["source_name"]
                                if mapping_data.get("target_name"):
                                    existing.target_name = mapping_data["target_name"]
                            else:
                                # Create new mapping
                                new_mapping = IDMapping(
                                    resource_type=mapping_data["resource_type"],
                                    source_id=mapping_data["source_id"],
                                    target_id=mapping_data.get("target_id"),
                                    source_name=mapping_data.get("source_name"),
                                    target_name=mapping_data.get("target_name"),
                                )
                                session.add(new_mapping)

                            total_processed += 1

                        # Commit entire batch
                        session.commit()
                        logger.debug(
                            "Batch commit complete",
                            batch_size=len(batch),
                            total_processed=total_processed,
                        )

                logger.info(
                    "Batch mappings complete",
                    total_mappings=total_processed,
                    num_batches=(len(mappings) + batch_size - 1) // batch_size,
                )
                return total_processed

            except Exception as e:
                logger.error(
                    "Failed to batch create mappings",
                    error=str(e),
                    batch_size=batch_size,
                )
                raise StateError(f"Failed to batch create mappings: {e}") from e

    def get_mapping_by_name(
        self,
        resource_type: str,
        source_name: str,
    ) -> IDMapping | None:
        """
        Get an ID mapping by resource name (fallback lookup during import).

        Args:
            resource_type: Type of resource
            source_name: Name in source system

        Returns:
            IDMapping object if found, None otherwise
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    mapping = (
                        session.query(IDMapping)
                        .filter_by(resource_type=resource_type, source_name=source_name)
                        .first()
                    )

                    # Detach from session before returning
                    if mapping:
                        session.expunge(mapping)

                    return mapping

            except Exception as e:
                logger.error(
                    "Failed to get mapping by name",
                    resource_type=resource_type,
                    source_name=source_name,
                    error=str(e),
                )
                return None

    def get_migration_stats(
        self,
        resource_type: str | None = None,
    ) -> dict[str, int]:
        """
        Get migration statistics.

        Args:
            resource_type: Optional resource type to filter by

        Returns:
            Dictionary with counts by status:
            {
                'total': 1000,
                'pending': 100,
                'in_progress': 50,
                'completed': 800,
                'failed': 40,
                'skipped': 10
            }
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    query = session.query(
                        MigrationProgress.status,
                        func.count(MigrationProgress.id).label("count"),
                    )

                    if resource_type:
                        query = query.filter(MigrationProgress.resource_type == resource_type)

                    results = query.group_by(MigrationProgress.status).all()

                    stats = {
                        "total": 0,
                        "pending": 0,
                        "in_progress": 0,
                        "completed": 0,
                        "failed": 0,
                        "skipped": 0,
                    }

                    for status, count in results:
                        stats[status] = count
                        stats["total"] += count

                    logger.debug(
                        "Retrieved migration stats",
                        resource_type=resource_type or "all",
                        stats=stats,
                    )

                    return stats

            except Exception as e:
                logger.error(
                    "Failed to get migration stats",
                    resource_type=resource_type,
                    error=str(e),
                )
                raise StateError(f"Failed to get migration stats: {e}") from e

    def reset_failed(
        self,
        resource_type: str | None = None,
        max_retries: int = 3,
    ) -> int:
        """
        Reset failed resources to pending status for retry.

        Args:
            resource_type: Optional resource type to filter by
            max_retries: Only reset resources with retry_count < max_retries

        Returns:
            Number of resources reset
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    query = session.query(MigrationProgress).filter(
                        MigrationProgress.status == "failed",
                        MigrationProgress.retry_count < max_retries,
                    )

                    if resource_type:
                        query = query.filter(MigrationProgress.resource_type == resource_type)

                    failed_resources = query.all()

                    count = 0
                    for resource in failed_resources:
                        resource.status = "pending"
                        resource.started_at = None
                        resource.completed_at = None
                        count += 1

                    session.commit()

                    logger.info(
                        "Reset failed resources",
                        resource_type=resource_type or "all",
                        count=count,
                        max_retries=max_retries,
                    )

                    return count

            except Exception as e:
                logger.error(
                    "Failed to reset failed resources",
                    resource_type=resource_type,
                    error=str(e),
                )
                raise StateError(f"Failed to reset failed resources: {e}") from e

    def clear_progress(
        self,
        resource_type: str | None = None,
    ) -> int:
        """
        Clear migration progress records to allow fresh re-export.

        Args:
            resource_type: Optional resource type to clear (None = all types)

        Returns:
            Number of progress records cleared
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    query = session.query(MigrationProgress)

                    if resource_type:
                        query = query.filter(MigrationProgress.resource_type == resource_type)

                    count = query.delete(synchronize_session=False)
                    session.commit()

                    logger.info(
                        "Cleared migration progress",
                        resource_type=resource_type or "all",
                        count=count,
                    )

                    return count

            except Exception as e:
                logger.error(
                    "Failed to clear migration progress",
                    resource_type=resource_type,
                    error=str(e),
                )
                raise StateError(f"Failed to clear migration progress: {e}") from e

    def reset_target_ids(self, resource_type: str) -> int:
        """
        Reset target_id to NULL for a resource type (preserves source mappings).

        This allows re-import without re-export. The source_id mappings
        created during export are preserved, only target_id is cleared.

        Use case: When import fails and you want to retry importing,
        but don't want to re-run the export process.

        Args:
            resource_type: Type of resource to reset

        Returns:
            Number of mappings reset

        Raises:
            StateError: If reset fails
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    query = session.query(IDMapping).filter(
                        IDMapping.resource_type == resource_type
                    )

                    # Update target_id and target_name to NULL
                    count = query.update(
                        {"target_id": None, "target_name": None},
                        synchronize_session=False,
                    )
                    session.commit()

                    logger.info(
                        "Reset target IDs",
                        resource_type=resource_type,
                        count=count,
                    )

                    return count

            except Exception as e:
                logger.error(
                    "Failed to reset target IDs",
                    resource_type=resource_type,
                    error=str(e),
                )
                raise StateError(f"Failed to reset target IDs: {e}") from e

    def reset_target_ids_for_source_ids(self, resource_type: str, source_ids: list[int]) -> int:
        """Reset target_id to NULL only for the given source IDs.

        Used by import batch precheck so clearing stale target IDs for one batch
        (e.g. smart inventories) does not wipe mappings for other resources of the
        same type already imported in an earlier step (e.g. static inventories).
        """
        if not source_ids:
            return 0
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    count = (
                        session.query(IDMapping)
                        .filter(
                            IDMapping.resource_type == resource_type,
                            IDMapping.source_id.in_(source_ids),
                        )
                        .update(
                            {"target_id": None, "target_name": None},
                            synchronize_session=False,
                        )
                    )
                    session.commit()

                    logger.info(
                        "Reset target IDs for source id subset",
                        resource_type=resource_type,
                        count=count,
                        source_id_count=len(source_ids),
                    )

                    return count

            except Exception as e:
                logger.error(
                    "Failed to reset target IDs for source subset",
                    resource_type=resource_type,
                    error=str(e),
                )
                raise StateError(f"Failed to reset target IDs for source subset: {e}") from e

    def export_state(self, output_path: str) -> None:
        """
        Export migration state to JSON file.

        Args:
            output_path: Path to output JSON file

        Raises:
            StateError: If export fails
        """
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    # Get all progress records
                    progress_records = session.query(MigrationProgress).all()
                    id_mappings = session.query(IDMapping).all()

                    export_data = {
                        "migration_id": self.migration_id,
                        "migration_name": self.migration_name,
                        "exported_at": datetime.now(UTC).isoformat(),
                        "stats": self.get_migration_stats(),
                        "progress": [
                            {
                                "resource_type": p.resource_type,
                                "source_id": p.source_id,
                                "source_name": p.source_name,
                                "target_id": p.target_id,
                                "status": p.status,
                                "phase": p.phase,
                                "retry_count": p.retry_count,
                                "error_message": p.error_message,
                            }
                            for p in progress_records
                        ],
                        "id_mappings": [
                            {
                                "resource_type": m.resource_type,
                                "source_id": m.source_id,
                                "target_id": m.target_id,
                                "source_name": m.source_name,
                                "target_name": m.target_name,
                            }
                            for m in id_mappings
                        ],
                    }

                    # Write to file
                    Path(output_path).write_text(json.dumps(export_data, indent=2))

                    logger.info(
                        "Exported migration state",
                        output_path=output_path,
                        record_count=len(progress_records),
                    )

            except Exception as e:
                logger.error("Failed to export state", output_path=output_path, error=str(e))
                raise StateError(f"Failed to export state: {e}") from e

    # ========================================================================
    # Transformation Phase Methods
    # ========================================================================
    # These methods are used during the transformation phase to:
    # 1. Register source resources in id_mappings with target_id=NULL
    # 2. Validate that dependencies exist before transforming dependent resources
    # ========================================================================

    def create_source_mapping(
        self,
        resource_type: str,
        source_id: int,
        source_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Create an id_mapping record during transformation (target_id=NULL).

        Called during transformation phase to register that a source resource
        was successfully exported and transformed. The target_id will be
        populated later during the import phase via mark_completed() or
        save_id_mapping().

        This method is idempotent - if a mapping already exists, it's skipped.

        Args:
            resource_type: Type of resource (e.g., 'inventories', 'hosts')
            source_id: Source system resource ID
            source_name: Name in source system (for debugging/audit)
            metadata: Optional metadata to store with the mapping

        Raises:
            StateError: If database operation fails
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    # Check if mapping already exists (idempotent)
                    existing = (
                        session.query(IDMapping)
                        .filter_by(resource_type=resource_type, source_id=source_id)
                        .first()
                    )

                    if existing:
                        logger.debug(
                            "source_mapping_exists",
                            resource_type=resource_type,
                            source_id=source_id,
                        )
                        return

                    # Create new mapping with target_id=NULL
                    mapping = IDMapping(
                        resource_type=resource_type,
                        source_id=source_id,
                        target_id=None,  # Will be set during import phase
                        source_name=source_name,
                        mapping_metadata=metadata,
                    )
                    session.add(mapping)
                    session.commit()

                    logger.debug(
                        "source_mapping_created",
                        resource_type=resource_type,
                        source_id=source_id,
                        source_name=source_name,
                    )

            except Exception as e:
                logger.error(
                    "Failed to create source mapping",
                    resource_type=resource_type,
                    source_id=source_id,
                    error=str(e),
                )
                raise StateError(f"Failed to create source mapping: {e}") from e

    def has_source_mapping(
        self,
        resource_type: str,
        source_id: int,
    ) -> bool:
        """
        Check if a source_id exists in id_mappings (regardless of target_id).

        Used during transformation to validate that dependencies were exported
        and transformed. This is different from has_mapping() which was designed
        for export resume - this method explicitly documents its use for
        dependency validation.

        Args:
            resource_type: Type of resource (e.g., 'inventories', 'hosts')
            source_id: Source system resource ID

        Returns:
            True if the source resource was exported/transformed, False otherwise
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    exists = (
                        session.query(IDMapping)
                        .filter_by(resource_type=resource_type, source_id=source_id)
                        .first()
                    ) is not None

                    logger.debug(
                        "checked_source_mapping",
                        resource_type=resource_type,
                        source_id=source_id,
                        exists=exists,
                    )

                    return exists

            except Exception as e:
                logger.error(
                    "Failed to check source mapping",
                    resource_type=resource_type,
                    source_id=source_id,
                    error=str(e),
                )
                raise StateError(f"Failed to check source mapping: {e}") from e

    def get_source_mapping_count(self, resource_type: str) -> int:
        """
        Get count of source mappings for a resource type.

        Useful for statistics and validation during transformation.

        Args:
            resource_type: Type of resource

        Returns:
            Count of source mappings (regardless of target_id)
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    count = (
                        session.query(func.count(IDMapping.id))
                        .filter(IDMapping.resource_type == resource_type)
                        .scalar()
                    )

                    return count or 0

            except Exception as e:
                logger.error(
                    "Failed to get source mapping count",
                    resource_type=resource_type,
                    error=str(e),
                )
                raise StateError(f"Failed to get source mapping count: {e}") from e

    def get_unmapped_count(self, resource_type: str) -> int:
        """
        Get count of resources transformed but not yet imported.

        Returns count of records where target_id IS NULL. Useful for
        tracking import progress.

        Args:
            resource_type: Type of resource

        Returns:
            Count of mappings with target_id=NULL
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    count = (
                        session.query(func.count(IDMapping.id))
                        .filter(
                            IDMapping.resource_type == resource_type,
                            IDMapping.target_id.is_(None),
                        )
                        .scalar()
                    )

                    return count or 0

            except Exception as e:
                logger.error(
                    "Failed to get unmapped count",
                    resource_type=resource_type,
                    error=str(e),
                )
                raise StateError(f"Failed to get unmapped count: {e}") from e

    def get_target_ids_for_type(self, resource_type: str) -> list[int]:
        """Get all target IDs for a resource type that have been successfully mapped.

        Useful for operations that need to work with all imported resources
        of a specific type (e.g., waiting for project sync after import).

        Args:
            resource_type: The resource type (e.g., "projects", "inventories")

        Returns:
            List of target IDs that have been mapped for this resource type
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    results = (
                        session.query(IDMapping.target_id)
                        .filter(
                            IDMapping.resource_type == resource_type,
                            IDMapping.target_id.isnot(None),
                        )
                        .all()
                    )
                    return [row[0] for row in results]

            except Exception as e:
                logger.error(
                    "Failed to get target IDs for type",
                    resource_type=resource_type,
                    error=str(e),
                )
                raise StateError(f"Failed to get target IDs for type: {e}") from e

    def import_state(self, input_path: str) -> None:
        """
        Import migration state from JSON file.

        Warning: This will overwrite existing state data!

        Args:
            input_path: Path to input JSON file

        Raises:
            StateError: If import fails
        """
        with self._lock:
            try:
                # Read import data
                import_data = json.loads(Path(input_path).read_text())

                with get_session(self.database_url) as session:
                    # Import progress records
                    for p_data in import_data.get("progress", []):
                        # Check if exists
                        existing = (
                            session.query(MigrationProgress)
                            .filter_by(
                                resource_type=p_data["resource_type"],
                                source_id=p_data["source_id"],
                            )
                            .first()
                        )

                        if existing:
                            # Update existing
                            existing.status = p_data["status"]
                            existing.target_id = p_data.get("target_id")
                            existing.phase = p_data["phase"]
                            existing.retry_count = p_data.get("retry_count", 0)
                            existing.error_message = p_data.get("error_message")
                        else:
                            # Create new
                            progress = MigrationProgress(
                                resource_type=p_data["resource_type"],
                                source_id=p_data["source_id"],
                                source_name=p_data["source_name"],
                                target_id=p_data.get("target_id"),
                                status=p_data["status"],
                                phase=p_data["phase"],
                                retry_count=p_data.get("retry_count", 0),
                                error_message=p_data.get("error_message"),
                            )
                            session.add(progress)

                    # Import ID mappings
                    for m_data in import_data.get("id_mappings", []):
                        existing_mapping = (
                            session.query(IDMapping)
                            .filter_by(
                                resource_type=m_data["resource_type"],
                                source_id=m_data["source_id"],
                            )
                            .first()
                        )

                        if existing_mapping:
                            existing_mapping.target_id = m_data["target_id"]
                            existing_mapping.source_name = m_data.get("source_name")
                            existing_mapping.target_name = m_data.get("target_name")
                        else:
                            mapping = IDMapping(
                                resource_type=m_data["resource_type"],
                                source_id=m_data["source_id"],
                                target_id=m_data["target_id"],
                                source_name=m_data.get("source_name"),
                                target_name=m_data.get("target_name"),
                            )
                            session.add(mapping)

                    session.commit()

                    logger.info(
                        "Imported migration state",
                        input_path=input_path,
                        progress_records=len(import_data.get("progress", [])),
                        id_mappings=len(import_data.get("id_mappings", [])),
                    )

            except Exception as e:
                logger.error("Failed to import state", input_path=input_path, error=str(e))
                raise StateError(f"Failed to import state: {e}") from e

    def get_all_resource_types(self) -> list[str]:
        """
        Get a list of all resource types currently tracked in the state.

        Returns:
            List of resource type names
        """
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    # Get distinct resource types from both tables
                    progress_types = session.query(MigrationProgress.resource_type).distinct().all()
                    mapping_types = session.query(IDMapping.resource_type).distinct().all()

                    all_types = set()
                    for (rtype,) in progress_types:
                        all_types.add(rtype)
                    for (rtype,) in mapping_types:
                        all_types.add(rtype)

                    return sorted(all_types)

            except Exception as e:
                logger.error("Failed to get all resource types", error=str(e))
                raise StateError(f"Failed to get all resource types: {e}") from e

    def get_all_mappings(
        self, resource_type: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get all ID mappings, optionally filtered by resource type.

        Args:
            resource_type: Optional resource type filter
            limit: Maximum number of records to return

        Returns:
            List of mapping dictionaries
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    query = session.query(IDMapping)
                    if resource_type:
                        query = query.filter(IDMapping.resource_type == resource_type)

                    mappings = query.limit(limit).all()

                    return [
                        {
                            "resource_type": m.resource_type,
                            "source_id": m.source_id,
                            "target_id": m.target_id,
                            "source_name": m.source_name,
                            "target_name": m.target_name,
                        }
                        for m in mappings
                    ]

            except Exception as e:
                logger.error("Failed to get mappings", error=str(e))
                raise StateError(f"Failed to get mappings: {e}") from e

    def get_overall_stats(self) -> dict[str, Any]:
        """Get overall migration statistics across all resource types.

        Returns:
            Dictionary with aggregated statistics
        """
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    # Count total mappings
                    total_mappings = session.query(IDMapping).count()

                    # Count total progress records
                    total_progress = session.query(MigrationProgress).count()

                    # Count completed resources
                    total_completed = (
                        session.query(MigrationProgress)
                        .filter(MigrationProgress.status == "completed")
                        .count()
                    )

                    # Count failed resources
                    total_failed = (
                        session.query(MigrationProgress)
                        .filter(MigrationProgress.status == "failed")
                        .count()
                    )

                    # Get counts by resource type
                    from sqlalchemy import func

                    type_counts = (
                        session.query(
                            MigrationProgress.resource_type,
                            func.count(MigrationProgress.source_id),
                        )
                        .filter(MigrationProgress.status == "completed")
                        .group_by(MigrationProgress.resource_type)
                        .all()
                    )

                    return {
                        "total_mappings": total_mappings,
                        "total_progress": total_progress,
                        "total_completed": total_completed,
                        "total_failed": total_failed,
                        "resource_counts": dict(type_counts),  # type: ignore[arg-type]
                    }

            except Exception as e:
                logger.error("Failed to get overall stats", error=str(e))
                raise StateError(f"Failed to get overall stats: {e}") from e

    def clear_mappings(self, resource_type: str, phase: str | None = None) -> int:
        """Delete id_mapping records for a resource type.

        Args:
            resource_type: Type of resource to clear mappings for
            phase: Optional phase filter (e.g., 'export')

        Returns:
            Number of records deleted
        """
        resource_type = self._normalize(resource_type)
        with self._lock:
            try:
                with get_session(self.database_url) as session:
                    query = session.query(IDMapping).filter(
                        IDMapping.resource_type == resource_type
                    )

                    # Note: phase is not currently in the IDMapping schema,
                    # but we'll filter by it if it ever is. For now, we clear all
                    # if no phase or if we assume export phase for these mappings.
                    # Currently, export mappings have target_id=None.
                    if phase == "export":
                        query = query.filter(IDMapping.target_id.is_(None))

                    count = query.delete(synchronize_session=False)
                    session.commit()

                    return count

            except Exception as e:
                logger.error(
                    "Failed to clear mappings",
                    resource_type=resource_type,
                    error=str(e),
                )
                raise StateError(f"Failed to clear mappings: {e}") from e
