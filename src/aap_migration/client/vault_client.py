"""HashiCorp Vault client for credential management.

This module provides a client for interacting with HashiCorp Vault
using AppRole authentication for managing AAP credentials.
"""

import time
from typing import Any

import hvac
from hvac.exceptions import VaultError as HvacVaultError

from aap_migration.client.exceptions import VaultAuthenticationError, VaultError
from aap_migration.config import VaultConfig
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


class VaultClient:
    """Client for HashiCorp Vault using AppRole authentication.

    This client manages:
    - AppRole authentication with automatic token renewal
    - KV2 secrets engine operations
    - Credential storage and retrieval
    - Batch operations for credentials
    """

    def __init__(self, config: VaultConfig):
        """Initialize Vault client.

        Args:
            config: Vault configuration with AppRole credentials
        """
        self.config = config
        self.vault_url = config.url
        self.role_id = config.role_id
        self.secret_id = config.secret_id
        self.namespace = config.namespace
        self.mount_point = config.mount_point
        self.path_prefix = config.path_prefix
        self.token_ttl = config.token_ttl

        # Initialize hvac client
        self.client = hvac.Client(
            url=self.vault_url,
            namespace=self.namespace,
            verify=config.verify_ssl,
        )

        # Track token expiration
        self._token_expires_at: float = 0
        self._authenticated = False

        # Authenticate on initialization
        self._authenticate()

        logger.info(
            "vault_client_initialized",
            url=self.vault_url,
            namespace=self.namespace,
            mount_point=self.mount_point,
            path_prefix=self.path_prefix,
        )

    def _authenticate(self) -> None:
        """Authenticate using AppRole and obtain a token."""
        try:
            logger.info("vault_authentication_starting")

            # Authenticate with AppRole
            auth_response = self.client.auth.approle.login(
                role_id=self.role_id,
                secret_id=self.secret_id,
            )

            # Set the token
            self.client.token = auth_response["auth"]["client_token"]

            # Track token expiration
            lease_duration = auth_response["auth"]["lease_duration"]
            self._token_expires_at = time.time() + lease_duration

            self._authenticated = True

            logger.info(
                "vault_authentication_successful",
                lease_duration=lease_duration,
                renewable=auth_response["auth"]["renewable"],
            )

        except HvacVaultError as e:
            logger.error("vault_authentication_failed", error=str(e))
            raise VaultAuthenticationError(f"Vault authentication failed: {str(e)}") from e
        except Exception as e:
            logger.error("vault_authentication_error", error=str(e), exc_info=True)
            raise VaultError(f"Unexpected error during authentication: {str(e)}") from e

    def _ensure_authenticated(self) -> None:
        """Ensure we have a valid token, renewing if necessary."""
        # Check if token is about to expire (within 5 minutes)
        if time.time() >= (self._token_expires_at - 300):
            logger.info("vault_token_expiring_soon", renewing=True)
            self._renew_token()

    def _renew_token(self) -> None:
        """Renew the current token or re-authenticate if renewal fails."""
        try:
            logger.info("vault_token_renewal_starting")

            renew_response = self.client.auth.token.renew_self()
            lease_duration = renew_response["auth"]["lease_duration"]
            self._token_expires_at = time.time() + lease_duration

            logger.info(
                "vault_token_renewed",
                new_lease_duration=lease_duration,
            )

        except HvacVaultError as e:
            logger.warning(
                "vault_token_renewal_failed",
                error=str(e),
                re_authenticating=True,
            )
            # If renewal fails, re-authenticate
            self._authenticate()

    def _build_secret_path(self, path: str) -> str:
        """Build full secret path with prefix.

        Args:
            path: Relative secret path

        Returns:
            Full secret path
        """
        # Remove leading/trailing slashes
        path = path.strip("/")
        prefix = self.path_prefix.strip("/")

        if not prefix:
            return path
        if not path:
            return prefix
        return f"{prefix}/{path}"

    def write_secret(
        self,
        path: str,
        secret_data: dict[str, Any],
        cas: int | None = None,
    ) -> dict[str, Any]:
        """Write a secret to Vault KV2 engine.

        Args:
            path: Secret path (will be prefixed with path_prefix)
            secret_data: Secret data dictionary
            cas: Check-And-Set parameter for optimistic locking

        Returns:
            Response data from Vault

        Raises:
            VaultError: If write operation fails
        """
        self._ensure_authenticated()

        full_path = self._build_secret_path(path)

        try:
            logger.info(
                "vault_write_secret",
                path=full_path,
                mount_point=self.mount_point,
                fields=list(secret_data.keys()),
            )

            response = self.client.secrets.kv.v2.create_or_update_secret(
                path=full_path,
                secret=secret_data,
                cas=cas,
                mount_point=self.mount_point,
            )

            logger.info(
                "vault_secret_written",
                path=full_path,
                version=response.get("data", {}).get("version"),
            )

            return dict(response)

        except HvacVaultError as e:
            logger.error("vault_write_failed", path=full_path, error=str(e))
            raise VaultError(f"Failed to write secret: {str(e)}") from e

    def read_secret(
        self,
        path: str,
        version: int | None = None,
    ) -> dict[str, Any]:
        """Read a secret from Vault KV2 engine.

        Args:
            path: Secret path (will be prefixed with path_prefix)
            version: Optional specific version to read

        Returns:
            Secret data dictionary

        Raises:
            VaultError: If read operation fails
        """
        self._ensure_authenticated()

        full_path = self._build_secret_path(path)

        try:
            logger.debug("vault_read_secret", path=full_path, version=version)

            response = self.client.secrets.kv.v2.read_secret_version(
                path=full_path,
                version=version,
                mount_point=self.mount_point,
            )

            # response["data"]["data"] is where the actual secret keys are
            secret_data = response.get("data", {}).get("data", {})

            logger.info("vault_secret_read", path=full_path, fields=list(secret_data.keys()))

            return dict(secret_data)

        except HvacVaultError as e:
            logger.error("vault_read_failed", path=full_path, error=str(e))
            raise VaultError(f"Failed to read secret: {str(e)}") from e

    def delete_secret(
        self,
        path: str,
        versions: list[int] | None = None,
    ) -> dict[str, Any]:
        """Delete a secret or specific versions.

        Args:
            path: Secret path (will be prefixed with path_prefix)
            versions: Optional list of specific versions to delete

        Returns:
            Response data from Vault

        Raises:
            VaultError: If delete operation fails
        """
        self._ensure_authenticated()

        full_path = self._build_secret_path(path)

        try:
            logger.info("vault_delete_secret", path=full_path, versions=versions)

            if versions:
                response = self.client.secrets.kv.v2.delete_secret_versions(
                    path=full_path,
                    versions=versions,
                    mount_point=self.mount_point,
                )
            else:
                response = self.client.secrets.kv.v2.delete_metadata_and_all_versions(
                    path=full_path,
                    mount_point=self.mount_point,
                )

            logger.info("vault_secret_deleted", path=full_path)

            return dict(response)

        except HvacVaultError as e:
            logger.error("vault_delete_failed", path=full_path, error=str(e))
            raise VaultError(f"Failed to delete secret: {str(e)}") from e

    def list_secrets(self, path: str = "") -> list[str]:
        """List secrets at a given path.

        Args:
            path: Path to list (will be prefixed with path_prefix)

        Returns:
            List of secret names

        Raises:
            VaultError: If list operation fails
        """
        self._ensure_authenticated()

        full_path = self._build_secret_path(path)

        try:
            logger.debug("vault_list_secrets", path=full_path)

            response = self.client.secrets.kv.v2.list_secrets(
                path=full_path,
                mount_point=self.mount_point,
            )

            secrets = response.get("data", {}).get("keys", [])

            logger.info("vault_secrets_listed", path=full_path, count=len(secrets))

            return list(secrets)

        except HvacVaultError as e:
            # Empty path returns 404
            if "404" in str(e):
                logger.debug("vault_list_empty", path=full_path)
                return []

            logger.error("vault_list_failed", path=full_path, error=str(e))
            raise VaultError(f"Failed to list secrets: {str(e)}") from e

    def secret_exists(self, path: str) -> bool:
        """Check if a secret exists.

        Args:
            path: Secret path (will be prefixed with path_prefix)

        Returns:
            True if secret exists, False otherwise
        """
        try:
            self.read_secret(path)
            return True
        except VaultError:
            return False

    def batch_write_secrets(
        self,
        secrets: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Write multiple secrets in batch.

        Args:
            secrets: Dictionary mapping paths to secret data

        Returns:
            Dictionary of results with success/failure information
        """
        results: dict[str, list[Any]] = {
            "successful": [],
            "failed": [],
        }

        total = len(secrets)
        logger.info("vault_batch_write_starting", total_secrets=total)

        for idx, (path, secret_data) in enumerate(secrets.items(), 1):
            try:
                self.write_secret(path, secret_data)
                results["successful"].append(path)

                if idx % 10 == 0:
                    logger.info(
                        "vault_batch_write_progress",
                        completed=idx,
                        total=total,
                        percentage=round(idx / total * 100, 2),
                    )

            except VaultError as e:
                logger.error("vault_batch_write_item_failed", path=path, error=str(e))
                results["failed"].append({"path": path, "error": str(e)})

        logger.info(
            "vault_batch_write_completed",
            total=total,
            successful=len(results["successful"]),
            failed=len(results["failed"]),
        )

        return results

    def validate_credential(
        self,
        path: str,
        required_fields: list[str],
    ) -> bool:
        """Validate that a credential has all required fields.

        Args:
            path: Secret path
            required_fields: List of required field names

        Returns:
            True if all required fields exist, False otherwise
        """
        try:
            secret_data = self.read_secret(path)

            missing_fields = [field for field in required_fields if field not in secret_data]

            if missing_fields:
                logger.warning(
                    "vault_credential_validation_failed",
                    path=path,
                    missing_fields=missing_fields,
                )
                return False

            logger.info("vault_credential_validated", path=path)
            return True

        except VaultError as e:
            logger.error("vault_credential_validation_error", path=path, error=str(e))
            return False

    def is_authenticated(self) -> bool:
        """Check if client is authenticated.

        Returns:
            True if authenticated, False otherwise
        """
        return self._authenticated and self.client.is_authenticated()

    def close(self) -> None:
        """Close the Vault client connection."""
        self.client.adapter.close()
        logger.info("vault_client_closed")
