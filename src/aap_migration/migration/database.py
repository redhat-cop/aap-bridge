"""
Database initialization and connection management utilities.

This module provides functions for initializing the migration database,
managing connections, and creating sessions with proper pooling and
thread safety.
"""

import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, pool, text
from sqlalchemy.orm import Session, sessionmaker

from aap_migration.client.exceptions import ConfigurationError, StateError
from aap_migration.migration.models import Base
from aap_migration.utils.logging import get_logger, redact_database_url

logger = get_logger(__name__)

# Global engine and session factory (initialized on first use)
_engine: Engine | None = None
_SessionFactory: sessionmaker | None = None


def normalize_database_url(db_path: str) -> str:
    """Return a SQLAlchemy-compatible URL from a DSN or filesystem path."""
    if db_path.startswith(("postgresql://", "sqlite://", "mysql://")):
        return db_path
    return f"sqlite:///{db_path}"


def _enable_sqlite_foreign_keys(dbapi_conn, connection_record):
    """
    Enable foreign key constraints for SQLite connections.

    SQLite has foreign keys disabled by default. This event handler
    enables them for each new connection.
    """
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_database_engine(
    database_url: str,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
    pool_recycle: int = 3600,
) -> Engine:
    """
    Create a SQLAlchemy engine with appropriate settings.

    Args:
        database_url: Database connection URL (sqlite:/// or postgresql://)
        echo: Whether to log SQL statements (useful for debugging)
        pool_size: Number of connections to maintain in the pool
        max_overflow: Maximum number of connections that can be created beyond pool_size
        pool_timeout: Timeout for getting a connection from the pool (seconds)
        pool_recycle: Recycle connections after this many seconds (prevents stale connections)

    Returns:
        SQLAlchemy Engine instance

    Raises:
        ConfigurationError: If database URL is invalid
    """
    if not database_url:
        raise ConfigurationError("Database URL cannot be empty")

    try:
        # Determine database type
        is_sqlite = database_url.startswith("sqlite")
        is_postgresql = database_url.startswith("postgresql")

        # Configure engine based on database type
        if is_sqlite:
            # SQLite-specific configuration
            # Use NullPool for SQLite to avoid threading issues
            engine = create_engine(
                database_url,
                echo=echo,
                poolclass=pool.NullPool,  # No connection pooling for SQLite
                connect_args={"check_same_thread": False},  # Allow multi-threaded access
            )
            # Enable foreign keys for SQLite
            event.listen(engine, "connect", _enable_sqlite_foreign_keys)

        elif is_postgresql:
            # PostgreSQL-specific configuration
            # Use QueuePool for PostgreSQL (default, with custom settings)
            engine = create_engine(
                database_url,
                echo=echo,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout,
                pool_pre_ping=True,  # Verify connections before using
                pool_recycle=pool_recycle,
            )

        else:
            # Generic configuration for other databases
            engine = create_engine(
                database_url,
                echo=echo,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout,
                pool_pre_ping=True,
            )

        logger.info(
            "Database engine created",
            database_type="sqlite" if is_sqlite else "postgresql" if is_postgresql else "other",
            pool_size=pool_size if not is_sqlite else "NullPool",
        )

        return engine

    except Exception as e:
        logger.error(
            "Failed to create database engine",
            error=str(e),
            database_url=redact_database_url(database_url),
        )
        raise ConfigurationError(f"Failed to create database engine: {e}") from e


def init_database(
    database_url: str,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
    pool_recycle: int = 3600,
) -> Engine:
    """
    Initialize the migration database.

    Creates all tables if they don't exist. This is idempotent and safe
    to call multiple times.

    Args:
        database_url: Database connection URL
        echo: Whether to log SQL statements
        pool_size: Number of connections to maintain in the pool
        max_overflow: Maximum number of connections that can be created beyond pool_size
        pool_timeout: Timeout for getting a connection from the pool (seconds)
        pool_recycle: Recycle connections after this many seconds

    Returns:
        SQLAlchemy Engine instance

    Raises:
        ConfigurationError: If database initialization fails
    """
    global _engine, _SessionFactory

    try:
        # Create engine
        _engine = create_database_engine(
            database_url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
        )

        # Create all tables
        Base.metadata.create_all(_engine)

        # Create session factory
        _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)

        logger.info(
            "Database initialized successfully",
            database_url=redact_database_url(database_url),
            tables=len(Base.metadata.tables),
        )

        return _engine

    except Exception as e:
        logger.error(
            "Failed to initialize database",
            error=str(e),
            database_url=redact_database_url(database_url),
        )
        raise ConfigurationError(f"Failed to initialize database: {e}") from e


def get_engine(database_url: str | None = None, echo: bool = False) -> Engine:
    """
    Get the global database engine.

    If the engine hasn't been initialized yet, this will initialize it.
    If database_url is not provided, uses the already-initialized engine.

    Args:
        database_url: Database connection URL (optional if already initialized)
        echo: Whether to log SQL statements

    Returns:
        SQLAlchemy Engine instance

    Raises:
        ConfigurationError: If engine is not initialized and no URL provided
    """
    global _engine

    if _engine is None:
        if database_url is None:
            raise ConfigurationError(
                "Database engine not initialized. Call init_database() first or provide database_url."
            )
        init_database(database_url, echo=echo)

    # Assert for type checker - init_database() guarantees _engine is not None
    assert _engine is not None, "Engine should be initialized by init_database()"
    return _engine


def get_session_factory() -> sessionmaker:
    """
    Get the global session factory.

    Returns:
        SQLAlchemy sessionmaker instance

    Raises:
        ConfigurationError: If session factory is not initialized
    """
    global _SessionFactory

    if _SessionFactory is None:
        raise ConfigurationError("Session factory not initialized. Call init_database() first.")

    return _SessionFactory


@contextmanager
def get_session(database_url: str | None = None) -> Generator[Session, None, None]:
    """
    Context manager for database sessions.

    Automatically commits on success and rolls back on exception.
    Always closes the session when done.

    Usage:
        with get_session() as session:
            session.add(obj)
            session.commit()  # Optional, will auto-commit on exit

    Args:
        database_url: Database connection URL (optional if already initialized)

    Yields:
        SQLAlchemy Session instance

    Raises:
        StateError: If database operation fails
    """
    # Ensure engine is initialized
    get_engine(database_url)

    # Get session factory
    session_factory = get_session_factory()

    # Create session
    session = session_factory()

    try:
        yield session
        session.commit()
        logger.debug("Database session committed successfully")

    except Exception as e:
        session.rollback()
        logger.error("Database session rolled back due to error", error=str(e))
        raise StateError(f"Database operation failed: {e}") from e

    finally:
        session.close()


def reset_database(database_url: str) -> None:
    """
    Drop all tables and recreate them.

    WARNING: This destroys all data in the database! Only use for testing
    or when you explicitly want to reset the migration state.

    Args:
        database_url: Database connection URL

    Raises:
        ConfigurationError: If database reset fails
    """
    try:
        engine = create_database_engine(database_url)

        # Drop all tables
        Base.metadata.drop_all(engine)
        logger.warning(
            "All database tables dropped", database_url=redact_database_url(database_url)
        )

        # Recreate all tables
        Base.metadata.create_all(engine)
        logger.info("Database tables recreated", database_url=redact_database_url(database_url))

        # Dispose of the engine
        engine.dispose()

    except Exception as e:
        logger.error(
            "Failed to reset database",
            error=str(e),
            database_url=redact_database_url(database_url),
        )
        raise ConfigurationError(f"Failed to reset database: {e}") from e


def validate_database_connection(database_url: str) -> bool:
    """
    Validate that a database connection can be established.

    Args:
        database_url: Database connection URL

    Returns:
        True if connection successful, False otherwise
    """
    try:
        engine = create_database_engine(database_url)
        with engine.connect() as conn:
            # Execute a simple query to verify connection
            conn.execute(text("SELECT 1"))
        engine.dispose()
        logger.info(
            "Database connection validated successfully",
            database_url=redact_database_url(database_url),
        )
        return True

    except Exception as e:
        logger.error(
            "Database connection validation failed",
            error=str(e),
            database_url=redact_database_url(database_url),
        )
        return False


def get_database_size(database_url: str) -> int:
    """
    Get the size of the database file (SQLite only).

    Args:
        database_url: Database connection URL (sqlite only)

    Returns:
        Database size in bytes, or 0 if not applicable/not found

    Raises:
        ValueError: If not a SQLite database
    """
    if not database_url.startswith("sqlite"):
        raise ValueError("Database size check only supported for SQLite databases")

    # Extract file path from URL
    # Format: sqlite:///path/to/file.db or sqlite:////absolute/path/to/file.db
    db_path = database_url.replace("sqlite:///", "")

    if not os.path.exists(db_path):
        return 0

    size_bytes = os.path.getsize(db_path)
    logger.debug("Database size checked", database_path=db_path, size_bytes=size_bytes)

    return size_bytes


def create_database_backup(database_url: str, backup_path: str) -> None:
    """
    Create a backup of the SQLite database (SQLite only).

    Args:
        database_url: Database connection URL (sqlite only)
        backup_path: Path where backup should be saved

    Raises:
        ValueError: If not a SQLite database
        ConfigurationError: If backup fails
    """
    import shutil

    if not database_url.startswith("sqlite"):
        raise ValueError("Database backup only supported for SQLite databases")

    try:
        # Extract file path from URL
        db_path = database_url.replace("sqlite:///", "")

        if not os.path.exists(db_path):
            raise ConfigurationError(f"Database file not found: {db_path}")

        # Create backup directory if it doesn't exist
        backup_dir = Path(backup_path).parent
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Copy database file
        shutil.copy2(db_path, backup_path)

        logger.info("Database backup created", source=db_path, backup=backup_path)

    except Exception as e:
        logger.error("Failed to create database backup", error=str(e))
        raise ConfigurationError(f"Failed to create database backup: {e}") from e
