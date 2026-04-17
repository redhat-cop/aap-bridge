"""Logging configuration for AAP Bridge using structlog.

This module configures structured logging with JSON output for production
and human-readable console output for development.
"""

import logging
from pathlib import Path
from typing import Any

import structlog
from rich.console import Console
from rich.logging import RichHandler
from structlog.typing import EventDict, WrappedLogger


def add_app_context(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """Add application context to log entries.

    Args:
        logger: The wrapped logger instance
        method_name: The name of the logger method called
        event_dict: The event dictionary to be logged

    Returns:
        EventDict: Modified event dictionary with app context
    """
    event_dict["app"] = "aap-bridge"
    event_dict["version"] = "0.1.0"
    return event_dict


def _strip_ansi_codes(text: str) -> str:
    """Remove ANSI escape codes from text.

    Args:
        text: Text potentially containing ANSI escape codes

    Returns:
        Text with all ANSI codes removed
    """
    import re

    ansi_pattern = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_pattern.sub("", text)


class JSONFileFormatter(logging.Formatter):
    """Custom formatter that outputs JSON for file logging.

    This formatter receives the already-rendered message from structlog
    (which uses ConsoleRenderer for readability) and converts it to JSON
    for file output. ANSI escape codes are stripped from the event message.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON."""
        import json

        # Get the message and strip any ANSI escape codes
        message = _strip_ansi_codes(record.getMessage())

        # Build JSON log entry from record attributes
        log_entry = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": message,
            "app": "aap-bridge",
            "version": "0.1.0",
        }

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def configure_logging(
    level: str = "WARNING",
    log_format: str = "json",
    log_file: str | None = None,
    file_level: str | None = None,
    enable_colors: bool = True,
) -> None:
    """Configure structured logging for the application.

    Args:
        level: Console log level (DEBUG, INFO, WARNING, ERROR, CRITICAL). Default: WARNING
        log_format: File output format ('json' for production, 'console' for development).
                   Console output always uses human-readable format.
        log_file: Optional path to log file
        file_level: File log level (defaults to DEBUG for detailed file logs)
        enable_colors: Enable colored output in console mode

    Note:
        - Console output is ALWAYS human-readable (never JSON) for clean CLI experience
        - File output uses JSON format by default for machine parsing
        - Console level defaults to WARNING to reduce clutter during migration
        - File logging (if enabled) defaults to DEBUG for comprehensive debugging
    """
    # Convert string level to logging constant
    console_level = getattr(logging, level.upper(), logging.WARNING)
    file_log_level = getattr(logging, (file_level or "DEBUG").upper(), logging.DEBUG)

    # Configure standard library logging with Rich integration
    # Create a shared Console instance for consistent rendering
    console = Console(stderr=True)  # Auto-detect terminal capabilities

    # Use RichHandler for console output - integrates properly with Rich's Live display
    # This prevents logging from interfering with progress bars
    rich_handler = RichHandler(
        console=console,
        show_time=False,  # structlog already adds timestamps
        show_path=False,  # We add logger names via structlog
        markup=True,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
    )
    rich_handler.setLevel(console_level)

    # Configure root logger with RichHandler
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Set to DEBUG, handlers will filter

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add RichHandler
    root_logger.addHandler(rich_handler)

    # Create log directory if log_file is specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

    # ALWAYS use console-friendly format for structlog output
    # This ensures clean CLI output - file handler uses JSONFileFormatter for JSON
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        add_app_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        structlog.dev.ConsoleRenderer(colors=False),  # RichHandler handles coloring
    ]

    # Configure structlog with console level
    # Note: structlog will respect the stdlib logging levels set above
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(console_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Add separate file handler with different log level if log_file specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(file_log_level)

        # Use JSON format for file output (machine-readable)
        # Use console format for file if explicitly requested
        if log_format == "json":
            file_handler.setFormatter(JSONFileFormatter())
        else:
            file_handler.setFormatter(logging.Formatter("%(message)s"))

        root_logger.addHandler(file_handler)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a configured logger instance.

    Args:
        name: Optional logger name (typically __name__)

    Returns:
        structlog.stdlib.BoundLogger: Configured logger instance
    """
    return structlog.get_logger(name)


def log_api_request(
    logger: structlog.stdlib.BoundLogger,
    method: str,
    url: str,
    status_code: int | None = None,
    duration_ms: float | None = None,
    **extra: Any,
) -> None:
    """Log an API request with structured data.

    Args:
        logger: Logger instance
        method: HTTP method (GET, POST, etc.)
        url: Request URL
        status_code: HTTP status code
        duration_ms: Request duration in milliseconds
        **extra: Additional context to log
    """
    log_data = {
        "method": method,
        "url": url,
        **extra,
    }

    if status_code is not None:
        log_data["status_code"] = status_code

    if duration_ms is not None:
        log_data["duration_ms"] = round(duration_ms, 2)

    # Choose log level based on status code
    if status_code is None:
        logger.info("api_request_started", **log_data)
    elif 200 <= status_code < 300:
        logger.info("api_request_success", **log_data)
    elif 400 <= status_code < 500:
        logger.warning("api_request_client_error", **log_data)
    elif 500 <= status_code < 600:
        logger.info("api_request_server_error", **log_data)
    else:
        logger.info("api_request_completed", **log_data)


def log_migration_progress(
    logger: structlog.stdlib.BoundLogger,
    phase: str,
    resource_type: str,
    completed: int,
    total: int,
    **extra: Any,
) -> None:
    """Log migration progress with structured data.

    Args:
        logger: Logger instance
        phase: Migration phase name
        resource_type: Type of resource being migrated
        completed: Number of items completed
        total: Total number of items
        **extra: Additional context to log
    """
    percentage = (completed / total * 100) if total > 0 else 0

    logger.info(
        "migration_progress",
        phase=phase,
        resource_type=resource_type,
        completed=completed,
        total=total,
        percentage=round(percentage, 2),
        **extra,
    )


def log_checkpoint(
    logger: structlog.stdlib.BoundLogger,
    checkpoint_name: str,
    phase: str,
    items_processed: int,
    **extra: Any,
) -> None:
    """Log checkpoint creation.

    Args:
        logger: Logger instance
        checkpoint_name: Name of the checkpoint
        phase: Migration phase
        items_processed: Number of items processed
        **extra: Additional context to log
    """
    logger.info(
        "checkpoint_created",
        checkpoint_name=checkpoint_name,
        phase=phase,
        items_processed=items_processed,
        **extra,
    )


def log_error(
    logger: structlog.stdlib.BoundLogger,
    error: Exception,
    context: str,
    **extra: Any,
) -> None:
    """Log an error with full context.

    Args:
        logger: Logger instance
        error: Exception that occurred
        context: Context where error occurred
        **extra: Additional context to log
    """
    logger.error(
        "error_occurred",
        error_type=type(error).__name__,
        error_message=str(error),
        context=context,
        **extra,
        exc_info=True,
    )


def sanitize_payload(payload: dict[str, Any] | list[Any] | Any, max_depth: int = 10) -> Any:
    """Sanitize sensitive fields in API payloads before logging.

    Recursively walks through the payload and replaces values of sensitive
    fields with "[REDACTED]" to prevent logging of secrets.

    Args:
        payload: The payload to sanitize (dict, list, or primitive)
        max_depth: Maximum recursion depth to prevent infinite loops

    Returns:
        Sanitized copy of the payload with sensitive values redacted

    Note:
        Sensitive field names (case-insensitive):
        - token, password, secret, api_key, ssh_key_data, ssh_key_unlock
        - private_key, vault_password, become_password, credential
        - authorization, auth_token, access_token, refresh_token
    """
    if max_depth <= 0:
        return "[MAX_DEPTH_EXCEEDED]"

    # Sensitive field names to redact (case-insensitive matching)
    sensitive_fields = {
        "token",
        "password",
        "secret",
        "api_key",
        "ssh_key_data",
        "ssh_key_unlock",
        "private_key",
        "vault_password",
        "become_password",
        "credential",
        "authorization",
        "auth_token",
        "access_token",
        "refresh_token",
        "client_secret",
        "vault_id",
        "secret_id",
    }

    if isinstance(payload, dict):
        sanitized = {}
        for key, value in payload.items():
            # Check if key matches any sensitive field (case-insensitive)
            if any(sensitive in key.lower() for sensitive in sensitive_fields):
                sanitized[key] = "[REDACTED]"
            elif isinstance(value, dict | list):
                sanitized[key] = sanitize_payload(value, max_depth - 1)
            else:
                sanitized[key] = value
        return sanitized

    elif isinstance(payload, list):
        return [sanitize_payload(item, max_depth - 1) for item in payload]

    else:
        # Primitive types (str, int, bool, None, etc.)
        return payload


def truncate_payload(payload: Any, max_size: int = 10000) -> str:
    """Convert payload to string and truncate if too large.

    Args:
        payload: The payload to convert and truncate
        max_size: Maximum size in characters

    Returns:
        String representation of payload, truncated if necessary
    """
    import json

    try:
        # Try to convert to JSON string for structured data
        payload_str = json.dumps(payload, indent=2, default=str)
    except (TypeError, ValueError):
        # Fallback to str() if JSON serialization fails
        payload_str = str(payload)

    if len(payload_str) > max_size:
        return payload_str[:max_size] + f"\n... [TRUNCATED - {len(payload_str)} total chars]"

    return payload_str


def should_log_payloads(logger: structlog.stdlib.BoundLogger, log_payloads_enabled: bool) -> bool:
    """Check if payload logging should be enabled.

    Payload logging requires:
    1. log_payloads config flag to be True
    2. Logger level to be DEBUG or lower

    Args:
        logger: Logger instance
        log_payloads_enabled: Value of log_payloads config flag

    Returns:
        True if payloads should be logged, False otherwise
    """
    if not log_payloads_enabled:
        return False

    # Check if logger is at DEBUG level
    # structlog loggers have _logger._logger attribute for stdlib logger
    try:
        stdlib_logger = logger._logger  # type: ignore
        return stdlib_logger.isEnabledFor(logging.DEBUG)
    except AttributeError:
        # Fallback: assume enabled if flag is True
        return True


# Example usage
if __name__ == "__main__":
    # Configure logging for console output
    configure_logging(level="DEBUG", log_format="console")

    # Get a logger
    logger = get_logger(__name__)

    # Log various events
    logger.info("application_started", environment="development")

    log_api_request(
        logger,
        method="GET",
        url="https://aap.example.com/api/v2/inventories/",
        status_code=200,
        duration_ms=125.5,
    )

    log_migration_progress(
        logger,
        phase="inventories",
        resource_type="inventory",
        completed=500,
        total=1000,
    )

    log_checkpoint(
        logger,
        checkpoint_name="inventories_batch_5",
        phase="inventories",
        items_processed=500,
    )

    # Simulate an error
    try:
        raise ValueError("Example error")
    except Exception as e:
        log_error(logger, e, context="example_operation")
