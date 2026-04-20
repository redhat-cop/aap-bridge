"""Configuration management for AAP Bridge using Pydantic.

This module provides type-safe configuration models for all aspects of the migration tool,
including AAP instances, Vault, performance tuning, and validation settings.
"""

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PathConfig(BaseModel):
    """Configuration for file paths."""

    base_dir: str = Field(default=".", description="Root directory for migration data")
    export_dir: str = Field(default="exports", description="Directory for exported data")
    transform_dir: str = Field(default="xformed", description="Directory for transformed data")
    schema_dir: str = Field(default="schemas", description="Directory for schema files")
    report_dir: str = Field(default="reports", description="Directory for migration reports")
    backup_dir: str = Field(default="backups", description="Directory for backups")
    mappings_file: str = Field(
        default="config/mappings.yaml",
        description="Path to mappings file (relative to project root)",
    )
    ignored_endpoints_file: str = Field(
        default="config/ignored_endpoints.yaml",
        description="Path to ignored endpoints file (relative to project root)",
    )


class PhasesConfig(BaseModel):
    """Configuration for migration phases."""

    organizations: bool = Field(default=True)
    users: bool = Field(default=True)
    teams: bool = Field(default=True)
    labels: bool = Field(default=True)
    credential_types: bool = Field(default=True)
    credentials: bool = Field(default=True)
    execution_environments: bool = Field(default=True)
    projects: bool = Field(default=True)
    inventory: bool = Field(default=True, alias="inventories")
    groups: bool = Field(default=True, alias="inventory_groups")
    inventory_sources: bool = Field(default=True)
    hosts: bool = Field(default=True)
    job_templates: bool = Field(default=True)
    workflow_job_templates: bool = Field(default=True)
    workflow_job_template_nodes: bool = Field(default=True, alias="workflow_nodes")
    schedules: bool = Field(default=True)
    rbac_assignments: bool = Field(default=True)

    model_config = ConfigDict(populate_by_name=True)


class AdvancedConfig(BaseModel):
    """Advanced migration options."""

    skip_existing: bool = Field(
        default=True, description="Skip resources that already exist on target"
    )
    force_update: bool = Field(default=False, description="Force update of existing resources")
    experimental_features: bool = Field(default=False, description="Enable experimental features")


class AAPInstanceConfig(BaseModel):
    """Configuration for an AAP instance (source or target)."""

    url: str = Field(..., description="AAP instance URL")
    token: str | None = Field(
        default=None,
        description="API authentication token (plain text, used when token_vault_path is not set)",
    )
    token_vault_path: str | None = Field(
        default=None,
        description="Vault secret path containing the API token (e.g., 'source' or 'target')",
    )
    version: str | None = Field(
        default=None,
        description="AAP version override (auto-detected if omitted)",
    )
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates")
    timeout: int = Field(default=30, ge=1, le=1200, description="API request timeout in seconds")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate and normalize URL."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        if not v.startswith("https://"):
            raise ValueError("URL should use HTTPS for security")
        return v.rstrip("/")

    @model_validator(mode="after")
    def validate_token_source(self) -> "AAPInstanceConfig":
        """Ensure either token or token_vault_path is provided."""
        if not self.token and not self.token_vault_path:
            raise ValueError("Either 'token' or 'token_vault_path' must be provided")
        return self


class VaultConfig(BaseModel):
    """Configuration for HashiCorp Vault integration."""

    url: str = Field(..., description="Vault server URL")
    role_id: str = Field(..., description="AppRole Role ID")
    secret_id: str = Field(..., description="AppRole Secret ID")
    namespace: str | None = Field(default=None, description="Vault namespace (optional)")
    mount_point: str = Field(
        default="secret",
        description="KV v2 secrets engine mount point",
    )
    path_prefix: str = Field(default="aap", description="Base path for secrets")
    verify_ssl: bool = Field(
        default=True,
        description="Verify Vault server TLS certificate",
    )
    token_ttl: int = Field(
        default=3600, ge=300, le=14400, description="Token TTL in seconds (5min - 4hrs)"
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate and normalize Vault URL."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("Vault URL must start with http:// or https://")
        return v.rstrip("/")

    @field_validator("path_prefix")
    @classmethod
    def validate_path_prefix(cls, v: str) -> str:
        """Validate path prefix format."""
        return v.strip("/")


class PerformanceConfig(BaseModel):
    """Performance tuning configuration."""

    batch_sizes: dict[str, int] = Field(
        default={
            "organizations": 200,
            "users": 200,
            "teams": 200,
            "labels": 200,
            "credential_types": 200,
            "credentials": 200,
            "execution_environments": 200,
            "projects": 200,
            "inventory": 200,
            "groups": 200,
            "inventory_sources": 200,
            "hosts": 200,  # API maximum - parallel fetching handles rate limiting
            "job_templates": 200,
            "workflow_job_templates": 200,
            "workflow_job_template_nodes": 200,
            "schedules": 200,
        },
        description="Batch sizes for different resource types (max 200 for AAP API)",
    )

    @field_validator("batch_sizes")
    @classmethod
    def validate_batch_sizes(cls, v: dict[str, int]) -> dict[str, int]:
        """Normalize batch_sizes keys to canonical names and validate values."""
        from aap_migration.resources import normalize_resource_type

        normalized = {}
        for k, val in v.items():
            if val < 1:
                raise ValueError(f"Batch size for {k} must be at least 1")

            canonical_name = normalize_resource_type(k)
            if canonical_name == "hosts" and val > 200:
                raise ValueError("Host batch size cannot exceed 200 (API limitation)")
            if val > 500:
                raise ValueError(f"Batch size for {k} should not exceed 500")

            normalized[canonical_name] = val
        return normalized

    max_concurrent: int = Field(
        default=15, ge=1, le=30, description="Maximum concurrent API requests"
    )
    rate_limit: int = Field(default=20, ge=1, le=50, description="Requests per second limit")
    memory_limit_mb: int = Field(default=8192, ge=1024, le=32768, description="Memory limit in MB")
    mapping_batch_size: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Number of ID mappings to commit in a single database transaction",
    )
    max_concurrent_pages: int = Field(
        default=10,
        ge=1,
        le=20,
        description="Maximum concurrent API page fetches for parallel export",
    )
    parallel_resource_types: bool = Field(
        default=False,
        description="Enable parallel export of different resource types (experimental)",
    )
    max_concurrent_types: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum resource types to export concurrently when parallel_resource_types is enabled",
    )
    cleanup_max_concurrent: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum concurrent deletions during cleanup",
    )
    cleanup_job_cancel_concurrency: int = Field(
        default=10,
        ge=1,
        le=25,
        description="Maximum concurrent job cancellations during cleanup (Platform Gateway safe limit)",
    )
    cleanup_page_fetch_concurrency: int = Field(
        default=10,
        ge=1,
        le=20,
        description="Maximum concurrent page fetches during cleanup resource discovery",
    )
    cleanup_job_finish_timeout: int = Field(
        default=300,
        ge=30,
        le=900,
        description="Timeout (seconds) waiting for canceled jobs to finish before proceeding with deletion",
    )
    cleanup_job_poll_interval: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Interval (seconds) between job status checks while waiting for jobs to finish",
    )
    user_import_max_concurrent: int = Field(
        default=25,
        ge=1,
        le=30,
        description="Maximum concurrent user import requests (higher than default since users have no dependencies)",
    )
    gateway_error_retry_attempts: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Number of retry attempts for gateway errors (502/503/504)",
    )
    gateway_error_backoff_base: float = Field(
        default=2.0,
        ge=1.0,
        le=5.0,
        description="Exponential backoff base multiplier for gateway error retries",
    )
    project_sync_timeout: int = Field(
        default=600,
        ge=60,
        le=1800,
        description="Timeout (seconds) waiting for project SCM sync to complete after import",
    )
    project_sync_poll_interval: int = Field(
        default=10,
        ge=5,
        le=60,
        description="Interval (seconds) between project sync status checks",
    )
    project_patch_batch_size: int = Field(
        default=100,
        ge=1,
        le=500,
        description="Number of projects to patch per batch in Phase 2",
    )
    project_patch_batch_interval: int = Field(
        default=180,
        ge=30,
        le=1800,
        description="Seconds to wait between project patch batches",
    )
    http_max_connections: int = Field(
        default=50,
        ge=10,
        le=200,
        description="Maximum number of connections in the connection pool",
    )
    http_max_keepalive_connections: int = Field(
        default=20,
        ge=5,
        le=100,
        description="Maximum number of keepalive connections",
    )
    default_page_size: int = Field(
        default=100,
        ge=1,
        le=200,
        description="Default page size for API requests",
    )
    bulk_operation_timeout: float = Field(
        default=300.0,
        ge=30.0,
        le=3600.0,
        description="Timeout for bulk operations in seconds",
    )
    host_import_concurrent_batches: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of concurrent batches for host import (speed vs load)",
    )
    host_cleanup_batch_size: int = Field(
        default=500,
        ge=1,
        le=500,
        description="Number of hosts to delete per batch during cleanup (max 500 - AAP limit)",
    )
    export_batch_size: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Batch size for parallel export operations",
    )
    retry_attempts: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Number of retry attempts for failed requests",
    )
    retry_backoff_min: int = Field(
        default=2,
        ge=1,
        le=60,
        description="Minimum backoff time in seconds for retries",
    )
    retry_backoff_max: int = Field(
        default=60,
        ge=5,
        le=300,
        description="Maximum backoff time in seconds for retries",
    )

    # Private caches for dummy values (generated once at first use, not from env/config)
    _cached_dummy_password: str | None = PrivateAttr(default=None)
    _cached_ssh_key: str | None = PrivateAttr(default=None)
    _cached_ssh_key_passphrase: str | None = PrivateAttr(default=None)
    _cached_encrypted_ssh_keys: dict[str, str] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def validate_gateway_safety(self) -> "PerformanceConfig":
        """Ensure cleanup settings won't overwhelm Platform Gateway.

        AAP 2.6 Platform Gateway can become overloaded with too many concurrent
        requests, leading to "no healthy upstream" errors. This validator enforces
        safe limits based on observed behavior.
        """
        if self.cleanup_job_cancel_concurrency > 25:
            raise ValueError(
                "cleanup_job_cancel_concurrency must be ≤25 to prevent "
                "Platform Gateway overload (no healthy upstream errors)"
            )
        return self

    # ==========================================================================
    # Cached Dummy Value Methods (for encrypted fields during migration)
    # ==========================================================================

    def get_dummy_password(self) -> str:
        """Get cached dummy password, generating once if needed.

        Used for encrypted fields like passwords, API keys, secrets.
        Generates a single value per session for performance.
        """
        if self._cached_dummy_password is None:
            import secrets

            self._cached_dummy_password = secrets.token_urlsafe(16)
        return self._cached_dummy_password

    def get_dummy_ssh_key_passphrase(self) -> str:
        """Get cached SSH key passphrase, generating once if needed.

        Used for ssh_key_unlock fields in credentials.
        """
        if self._cached_ssh_key_passphrase is None:
            import secrets

            self._cached_ssh_key_passphrase = secrets.token_urlsafe(16)
        return self._cached_ssh_key_passphrase

    def get_dummy_ssh_key(self) -> str:
        """Get cached unencrypted SSH key, generating once if needed.

        Generates a valid 2048-bit RSA private key in PEM format.
        """
        if self._cached_ssh_key is None:
            from aap_migration.migration.transformer import generate_temp_ssh_key

            self._cached_ssh_key = generate_temp_ssh_key()
        return self._cached_ssh_key

    def get_dummy_encrypted_ssh_key(self, passphrase: str) -> str:
        """Get cached encrypted SSH key for passphrase, generating once if needed.

        Generates a valid 2048-bit RSA private key encrypted with the passphrase.
        Caches per unique passphrase.
        """
        if passphrase not in self._cached_encrypted_ssh_keys:
            from aap_migration.migration.transformer import generate_temp_encrypted_ssh_key

            self._cached_encrypted_ssh_keys[passphrase] = generate_temp_encrypted_ssh_key(
                passphrase
            )
        return self._cached_encrypted_ssh_keys[passphrase]


class StateConfig(BaseModel):
    """State management configuration."""

    db_path: str = Field(default="./migration_state.db", description="Path to state database file")
    checkpoint_frequency: int = Field(
        default=100, ge=10, le=1000, description="Items between checkpoints"
    )
    backup_enabled: bool = Field(default=True, description="Enable state database backups")
    db_pool_size: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Number of connections to maintain in the pool (PostgreSQL only)",
    )
    db_max_overflow: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of connections to create beyond pool_size (PostgreSQL only)",
    )
    db_pool_timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Timeout in seconds for getting a connection from the pool",
    )
    db_pool_recycle: int = Field(
        default=3600,
        ge=60,
        le=28800,
        description="Recycle connections after this many seconds",
    )


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = Field(
        default="WARNING",
        description="Console log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    file_level: str = Field(
        default="DEBUG",  # Detailed file logs for debugging
        description="File log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    format: str = Field(default="json", description="Log format (json or console)")
    file: str | None = Field(default="logs/migration.log", description="Log file path")
    rotation: str = Field(default="daily", description="Log rotation policy")
    retention_days: int = Field(default=30, ge=1, le=365, description="Log retention in days")

    # Progress display options
    disable_progress: bool = Field(
        default=False, description="Disable live progress display (useful for CI/logging)"
    )
    show_stats: bool = Field(default=False, description="Show detailed statistics and timings")

    # Payload logging options (for debugging)
    log_payloads: bool = Field(
        default=False,
        description=(
            "Enable request/response payload logging at DEBUG level. "
            "WARNING: May log sensitive data (tokens will be redacted)."
        ),
    )
    max_payload_size: int = Field(
        default=10000,
        ge=100,
        le=1000000,
        description="Maximum payload size (characters) to log. Larger payloads will be truncated.",
    )

    @field_validator("level", "file_level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"Log level must be one of: {', '.join(valid_levels)}")
        return v_upper

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        """Validate log format."""
        valid_formats = ["json", "console"]
        v_lower = v.lower()
        if v_lower not in valid_formats:
            raise ValueError(f"Log format must be one of: {', '.join(valid_formats)}")
        return v_lower


class ValidationConfig(BaseModel):
    """Validation configuration."""

    statistical_sample_size: int = Field(
        default=4000, ge=100, le=10000, description="Sample size for statistical validation"
    )
    confidence_level: float = Field(
        default=0.99, ge=0.90, le=0.99, description="Confidence level (0.90 - 0.99)"
    )
    margin_of_error: float = Field(
        default=0.02, ge=0.01, le=0.10, description="Margin of error (0.01 - 0.10)"
    )
    validate_after_each_phase: bool = Field(
        default=True, description="Run validation after each migration phase"
    )


# Default execution environment names often skipped (platform / hub defaults)
DEFAULT_SKIP_EXECUTION_ENVIRONMENT_NAMES: tuple[str, ...] = (
    "Control Plane Execution Environment",
    "Default execution environment",
    "Hub Default execution environment",
    "Hub Minimal execution environment",
    "Minimal execution environment",
)


def normalized_execution_environment_skip_names(names: list[str] | None) -> frozenset[str]:
    """Normalize EE display names for case-insensitive matching."""
    if not names:
        return frozenset()
    return frozenset(s.strip().casefold() for s in names if s and str(s).strip())


class ExportConfig(BaseModel):
    """Export configuration options."""

    skip_dynamic_hosts: bool = Field(
        default=True,
        description="Skip hosts with inventory sources (filter: inventory_sources__isnull=true)",
    )
    skip_smart_inventories: bool = Field(
        default=True,
        description=(
            "Skip smart inventories (kind='smart') during export and transform. "
            "When false, smart inventories are exported and imported like regular inventories."
        ),
    )
    skip_constructed_inventories: bool = Field(
        default=True,
        description=(
            "Skip constructed inventories (kind='constructed') during export and transform. "
            "When false, constructed inventories are exported and routed to the "
            "constructed_inventories/ endpoint on target during import."
        ),
    )
    skip_inventory_sources: list[str] = Field(
        default_factory=list,
        description="List of inventory source types to skip (e.g., ['scm', 'ec2', 'custom'])",
    )
    skip_pending_deletion_inventories: bool = Field(
        default=True,
        description=(
            "Skip inventories marked for deletion (pending_deletion=true). "
            "Uses API filter: pending_deletion=false"
        ),
    )
    skip_hosts_with_inventory_sources: bool = Field(
        default=True,
        description=(
            "Export/transform: skip hosts managed by inventory sources (has_inventory_sources=true). "
            "Import also skips bulk host/group create when the target inventory already has "
            "inventory_sources (after they are migrated); run an inventory update on the target "
            "to populate hosts and groups from SCM, Satellite, cloud, etc."
        ),
    )
    skip_execution_environment_names: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SKIP_EXECUTION_ENVIRONMENT_NAMES),
        description=(
            "Execution environment `name` values to omit from export and import "
            "(case-insensitive). Edit this list in config; use [] to include all EEs."
        ),
    )
    records_per_file: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Number of records per exported JSON file",
    )
    filters: dict[str, str] = Field(
        default_factory=dict,
        description="Optional API filters for resources (e.g., {'name__icontains': 'test'})",
    )


class TransformConfig(BaseModel):
    """Transform phase configuration options.

    Note: Export-phase filtering is preferred for efficiency.
    Transform-phase filtering serves as a safety net for resources
    that slip through if export filters are disabled.
    """

    skip_pending_deletion: bool = Field(
        default=True,
        description=(
            "Skip inventories marked for deletion (pending_deletion=true). "
            "Note: Export-phase filtering (skip_pending_deletion_inventories) is preferred. "
            "This serves as a safety net for resources that slip through."
        ),
    )


class MigrationConfig(BaseSettings):
    """Main migration configuration."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    # AAP Instances
    source: AAPInstanceConfig = Field(..., description="Source AAP configuration")
    target: AAPInstanceConfig = Field(..., description="Target AAP configuration")

    # Vault (optional)
    vault: VaultConfig | None = Field(default=None, description="Vault configuration")

    # Paths
    paths: PathConfig = Field(default_factory=PathConfig, description="Path configuration")

    # Performance tuning
    performance: PerformanceConfig = Field(
        default_factory=PerformanceConfig, description="Performance configuration"
    )

    # State management
    state: StateConfig = Field(default_factory=StateConfig, description="State configuration")

    # Logging
    logging: LoggingConfig = Field(
        default_factory=LoggingConfig, description="Logging configuration"
    )

    # Validation
    validation: ValidationConfig = Field(
        default_factory=ValidationConfig, description="Validation configuration"
    )

    # Export options
    export: ExportConfig = Field(default_factory=ExportConfig, description="Export configuration")

    # Transform options
    transform: TransformConfig = Field(
        default_factory=TransformConfig, description="Transform configuration"
    )

    # Phases
    phases: PhasesConfig = Field(default_factory=PhasesConfig, description="Phase configuration")

    # Advanced options
    advanced: AdvancedConfig = Field(
        default_factory=AdvancedConfig, description="Advanced configuration"
    )

    # Migration options
    dry_run: bool = Field(default=False, description="Dry run mode (no actual changes)")
    resume: bool = Field(default=False, description="Resume from last checkpoint")
    skip_validation: bool = Field(default=False, description="Skip validation steps")

    # Resource Mappings (loaded from external file)
    resource_mappings: dict[str, dict[str, str]] = Field(
        default_factory=dict, description="Resource renaming rules"
    )

    # Ignored Endpoints (loaded from external file)
    ignored_endpoints: dict[str, list[str]] = Field(
        default_factory=lambda: {"common": [], "source": [], "target": []},
        description="Endpoints to ignore grouped by scope (common, source, target)",
    )

    @model_validator(mode="after")
    def load_resource_mappings_from_file(self) -> "MigrationConfig":
        """Load resource mappings from the configured file if not already populated."""
        if not self.resource_mappings and self.paths.mappings_file:
            mappings_path = Path(self.paths.mappings_file)
            if mappings_path.exists():
                try:
                    with open(mappings_path) as f:
                        mappings_data = yaml.safe_load(f)
                        if mappings_data:
                            self.resource_mappings = mappings_data
                except Exception:
                    pass
        return self

    @model_validator(mode="after")
    def load_ignored_endpoints_from_file(self) -> "MigrationConfig":
        """Load ignored endpoints from the configured file if not already populated."""
        if self.paths.ignored_endpoints_file:
            ignored_path = Path(self.paths.ignored_endpoints_file)
            if ignored_path.exists():
                try:
                    with open(ignored_path) as f:
                        ignored_data = yaml.safe_load(f)
                        if ignored_data and "ignored_endpoints" in ignored_data:
                            raw_ignored = ignored_data["ignored_endpoints"]
                            # Handle both old list format and new dict format
                            if isinstance(raw_ignored, list):
                                self.ignored_endpoints = {
                                    "common": raw_ignored,
                                    "source": [],
                                    "target": [],
                                }
                            elif isinstance(raw_ignored, dict):
                                self.ignored_endpoints = {
                                    "common": raw_ignored.get("common") or [],
                                    "source": raw_ignored.get("source") or [],
                                    "target": raw_ignored.get("target") or [],
                                }
                except Exception:
                    pass
        return self


def load_config_from_yaml(config_path: str | Path) -> MigrationConfig:
    """Load configuration from YAML file.

    Args:
        config_path: Path to YAML configuration file

    Returns:
        MigrationConfig: Loaded configuration

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file is invalid
    """
    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path) as f:
        config_data = yaml.safe_load(f)

    if not config_data:
        raise ValueError(f"Empty configuration file: {config_path}")

    # Expand environment variables in the config
    config_data = _expand_env_vars(config_data)

    return MigrationConfig(**config_data)


def _expand_env_vars(data: dict) -> dict:
    """Recursively expand environment variables in config dict.

    Supports ${VAR_NAME} syntax for environment variable substitution.

    Args:
        data: Configuration dictionary

    Returns:
        dict: Dictionary with expanded environment variables
    """
    if isinstance(data, dict):
        return {k: _expand_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_expand_env_vars(item) for item in data]
    elif isinstance(data, str):
        # Replace ${VAR_NAME} with environment variable value
        if data.startswith("${") and data.endswith("}"):
            var_name = data[2:-1]
            env_value = os.environ.get(var_name)
            if env_value is None:
                raise ValueError(
                    f"Environment variable '{var_name}' not found. "
                    f"Please set it in your environment or .env file."
                )
            return env_value
        return data
    else:
        return data


def save_config_to_yaml(config: MigrationConfig, output_path: str | Path) -> None:
    """Save configuration to YAML file.

    Args:
        config: Configuration to save
        output_path: Path to output YAML file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to dict and remove sensitive values
    config_dict = config.model_dump()

    with open(output_path, "w") as f:
        yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)
