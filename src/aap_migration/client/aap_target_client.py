"""AAP 2.6 Target Client for importing resources.

This client provides methods to create resources in AAP 2.6 with
Platform Gateway support and bulk operations.
"""

from typing import Any

from aap_migration.client.api_layout import normalize_host_url
from aap_migration.client.base_client import BaseAPIClient
from aap_migration.client.exceptions import ConflictError
from aap_migration.config import AAPInstanceConfig
from aap_migration.resources import get_endpoint
from aap_migration.utils.logging import get_logger
from aap_migration.utils.retry import retry_api_call

logger = get_logger(__name__)


class AAPTargetClient(BaseAPIClient):
    """Client for AAP 2.6 target instance.

    This client extends BaseAPIClient with AAP 2.6-specific methods for
    creating resources, including bulk operations support. It handles
    the Platform Gateway routing automatically.
    """

    def __init__(
        self,
        config: AAPInstanceConfig,
        rate_limit: int = 20,
        log_payloads: bool = False,
        max_payload_size: int = 10000,
        max_connections: int | None = None,
        max_keepalive_connections: int | None = None,
    ):
        """Initialize AAP target client.

        Args:
            config: AAP instance configuration (host URL; API paths are auto-discovered)
            rate_limit: Maximum requests per second
            log_payloads: Enable request/response payload logging
            max_payload_size: Maximum payload size to log before truncation
            max_connections: Maximum number of connections in pool
            max_keepalive_connections: Maximum keep-alive connections
        """
        if config.token is None:
            raise ValueError("API token must be resolved before initializing AAPTargetClient")
        if not config.version:
            raise ValueError(
                "TARGET__VERSION must be set; target AAP version cannot be detected "
                "reliably from the API on older releases."
            )

        super().__init__(
            host_url=normalize_host_url(config.url),
            token=config.token,
            aap_version=config.version,
            verify_ssl=config.verify_ssl,
            timeout=config.timeout,
            rate_limit=rate_limit,
            log_payloads=log_payloads,
            max_payload_size=max_payload_size,
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
        )
        logger.info("aap_target_client_initialized", url=self.host_url, version=config.version)

    async def get_version(self) -> str:
        """Return the configured target AAP version."""
        return self.aap_version

    # Core CRUD operations
    @retry_api_call
    async def create_resource(
        self,
        resource_type: str,
        data: dict[str, Any],
        check_exists: bool = True,
    ) -> dict[str, Any]:
        """Create a resource in AAP 2.6.

        Args:
            resource_type: Resource type (e.g., 'inventories', 'hosts')
            data: Resource data
            check_exists: Check if resource exists before creating (idempotency)

        Returns:
            Created resource data

        Raises:
            ConflictError: If resource already exists (409)
        """
        endpoint = get_endpoint(resource_type)

        try:
            result = await self.post(endpoint, json_data=data)
            logger.info(
                "resource_created",
                resource_type=resource_type,
                resource_id=result.get("id"),
                resource_name=result.get("name"),
            )
            return result
        except ConflictError:
            if check_exists:
                logger.info(
                    "resource_already_exists",
                    resource_type=resource_type,
                    resource_name=data.get("name"),
                )
                # Try to find the existing resource
                existing = await self.find_resource_by_name(resource_type, data.get("name", ""))
                if existing:
                    return existing
            raise

    @retry_api_call
    async def update_resource(
        self,
        resource_type: str,
        resource_id: int,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a resource in AAP 2.6.

        Args:
            resource_type: Resource type (e.g., 'inventories', 'hosts')
            resource_id: Resource ID
            data: Resource data to update

        Returns:
            Updated resource data
        """
        base = get_endpoint(resource_type).rstrip("/")
        endpoint = f"{base}/{resource_id}/"
        result = await self.patch(endpoint, json_data=data)
        logger.info(
            "resource_updated",
            resource_type=resource_type,
            resource_id=resource_id,
        )
        return result

    @retry_api_call
    async def delete_resource(
        self,
        resource_type: str,
        resource_id: int,
    ) -> dict[str, Any]:
        """Delete a resource from AAP 2.6.

        Args:
            resource_type: Resource type (e.g., 'inventories', 'hosts')
            resource_id: Resource ID

        Returns:
            Empty dict or deletion confirmation
        """
        base = get_endpoint(resource_type).rstrip("/")
        endpoint = f"{base}/{resource_id}/"
        result = await self.delete(endpoint)
        logger.info(
            "resource_deleted",
            resource_type=resource_type,
            resource_id=resource_id,
        )
        return result

    @retry_api_call
    async def get_resource(
        self,
        resource_type: str,
        resource_id: int,
    ) -> dict[str, Any]:
        """Get a resource from AAP 2.6.

        Args:
            resource_type: Resource type (e.g., 'inventories', 'hosts')
            resource_id: Resource ID

        Returns:
            Resource data
        """
        base = get_endpoint(resource_type).rstrip("/")
        endpoint = f"{base}/{resource_id}/"
        return await self.get(endpoint)

    @retry_api_call
    async def resource_exists(
        self,
        resource_type: str,
        resource_id: int,
    ) -> bool:
        """Check if a resource exists.

        Args:
            resource_type: Resource type (e.g., 'inventories', 'hosts')
            resource_id: Resource ID

        Returns:
            True if resource exists, False otherwise
        """
        try:
            await self.get_resource(resource_type, resource_id)
            return True
        except Exception:
            return False

    @retry_api_call
    async def find_resource_by_name(
        self,
        resource_type: str,
        name: str,
        organization: str | None = None,
    ) -> dict[str, Any] | None:
        """Find a resource by name.

        Args:
            resource_type: Resource type (e.g., 'inventories', 'hosts')
            name: Resource name
            organization: Optional organization name to filter by

        Returns:
            Resource data if found, None otherwise
        """
        params: dict[str, Any] = {"name": name, "page_size": 1}
        if organization:
            params["organization__name"] = organization

        endpoint = get_endpoint(resource_type)
        response = await self.get(endpoint, params=params)

        results = response.get("results", [])
        return results[0] if results else None

    # Specific resource creation methods
    @retry_api_call
    async def create_organization(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create an organization.

        Args:
            data: Organization data

        Returns:
            Created organization
        """
        return await self.create_resource("organizations", data)

    @retry_api_call
    async def create_inventory(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create an inventory.

        Args:
            data: Inventory data

        Returns:
            Created inventory
        """
        return await self.create_resource("inventories", data)

    @retry_api_call
    async def create_host(self, inventory_id: int, data: dict[str, Any]) -> dict[str, Any]:
        """Create a single host.

        For creating multiple hosts, use bulk_create_hosts instead.

        Args:
            inventory_id: Inventory ID
            data: Host data

        Returns:
            Created host
        """
        data["inventory"] = inventory_id
        return await self.create_resource("hosts", data)

    @retry_api_call
    async def create_credential(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a credential.

        Args:
            data: Credential data

        Returns:
            Created credential
        """
        return await self.create_resource("credentials", data)

    @retry_api_call
    async def create_project(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a project.

        Args:
            data: Project data

        Returns:
            Created project
        """
        return await self.create_resource("projects", data)

    @retry_api_call
    async def create_job_template(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a job template.

        Args:
            data: Job template data

        Returns:
            Created job template
        """
        return await self.create_resource("job_templates", data)

    @retry_api_call
    async def create_workflow_job_template(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a workflow job template.

        Args:
            data: Workflow job template data

        Returns:
            Created workflow job template
        """
        return await self.create_resource("workflow_job_templates", data)

    # Job operations
    @retry_api_call
    async def launch_job_template(
        self,
        job_template_id: int,
        extra_vars: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Launch a job template.

        Args:
            job_template_id: Job template ID
            extra_vars: Optional extra variables

        Returns:
            Job data
        """
        endpoint = f"job_templates/{job_template_id}/launch/"
        data = {"extra_vars": extra_vars} if extra_vars else {}
        return await self.post(endpoint, json_data=data)

    @retry_api_call
    async def get_job_status(self, job_id: int) -> dict[str, Any]:
        """Get job status.

        Args:
            job_id: Job ID

        Returns:
            Job data with status
        """
        endpoint = f"jobs/{job_id}/"
        return await self.get(endpoint)

    @retry_api_call
    async def cancel_job(self, job_id: int, endpoint_prefix: str = "jobs") -> dict[str, Any]:
        """Cancel a running job (AWX-inspired implementation).

        This method implements AWX best practices:
        1. Check current job status first
        2. Verify job is not already finished
        3. Check if job can be cancelled (can_cancel field)
        4. Handle race conditions gracefully

        Args:
            job_id: Job ID to cancel
            endpoint_prefix: Job endpoint (e.g., "jobs", "workflow_jobs", "project_updates")

        Returns:
            Updated job data after cancellation (or current status if already finished)

        Raises:
            APIError: If cancellation fails (excluding expected cases)

        Example:
            >>> job = await client.cancel_job(12345, "workflow_jobs")
            >>> print(job["status"])  # "canceling" or "canceled"
        """
        from aap_migration.resources import JOB_TERMINAL_STATUSES, JOB_TRANSIENT_STATUSES
        from aap_migration.utils.logging import get_logger

        logger = get_logger(__name__)

        # 1. Get current job status first
        job_endpoint = f"{endpoint_prefix}/{job_id}/"
        try:
            job = await self.get(job_endpoint)
        except Exception as e:
            logger.error(
                "failed_to_get_job_status", job_id=job_id, endpoint=endpoint_prefix, error=str(e)
            )
            raise

        current_status = job.get("status", "unknown")

        # 2. Check if job is already finished or canceling
        if current_status in JOB_TERMINAL_STATUSES:
            logger.info(
                "job_already_finished",
                job_id=job_id,
                endpoint=endpoint_prefix,
                status=current_status,
            )
            return job

        if current_status in JOB_TRANSIENT_STATUSES:
            logger.info(
                "job_already_canceling",
                job_id=job_id,
                endpoint=endpoint_prefix,
                status=current_status,
            )
            return job

        # 3. Check if job can be cancelled (AWX pattern)
        can_cancel = job.get("can_cancel", True)  # Default True for backward compatibility
        if not can_cancel:
            logger.warning(
                "job_not_cancellable",
                job_id=job_id,
                endpoint=endpoint_prefix,
                status=current_status,
                can_cancel=can_cancel,
            )
            return job

        # 4. POST to cancel endpoint
        cancel_endpoint = f"{endpoint_prefix}/{job_id}/cancel/"
        try:
            result = await self.post(cancel_endpoint, json_data={})
            logger.info(
                "job_cancelled_successfully",
                job_id=job_id,
                endpoint=endpoint_prefix,
                previous_status=current_status,
            )
            return result
        except Exception as e:
            # Handle race condition - job may have finished between check and cancel
            if hasattr(e, "status_code") and e.status_code == 405:
                # Method not allowed - this job type doesn't support cancellation
                logger.debug(
                    "job_type_does_not_support_cancel",
                    job_id=job_id,
                    endpoint=endpoint_prefix,
                    status_code=405,
                )
                raise  # Let caller handle 405
            elif "not allowed" in str(e).lower():
                logger.info(
                    "job_finished_during_cancel_attempt",
                    job_id=job_id,
                    endpoint=endpoint_prefix,
                    error=str(e),
                )
                # Return refreshed status
                return await self.get(job_endpoint)
            else:
                # Unexpected error
                logger.error(
                    "job_cancel_failed",
                    job_id=job_id,
                    endpoint=endpoint_prefix,
                    error=str(e),
                    status_code=getattr(e, "status_code", None),
                )
                raise

    # Validation and count methods
    async def get_count(self, resource_type: str) -> int:
        """Get count of resources.

        Args:
            resource_type: Resource type (e.g., 'inventories', 'hosts')

        Returns:
            Count of resources
        """
        endpoint = get_endpoint(resource_type)
        response = await self.get(endpoint, params={"page_size": 1})
        return response.get("count", 0)

    @retry_api_call
    async def list_resources(
        self,
        resource_type: str,
        filters: dict[str, Any] | None = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """List resources with optional filters and automatic pagination.

        Args:
            resource_type: Resource type (e.g., 'users', 'organizations')
            filters: Query filters (e.g., {"name__in": "user1,user2,user3"})
            page_size: Number of results per page (default: 100)

        Returns:
            List of all matching resources (all pages combined)

        Example:
            # Batch query users by username
            users = await client.list_resources(
                "users",
                filters={"username__in": "alice,bob,charlie"}
            )
        """
        # Use get_endpoint to map resource_type to correct API endpoint
        # (e.g., "inventory_groups" -> "groups/")
        endpoint = get_endpoint(resource_type)
        params = {"page_size": page_size}

        if filters:
            params.update(filters)

        all_results = []

        # Handle pagination automatically
        while endpoint:
            response = await self.get(endpoint, params=params)
            results = response.get("results", [])
            all_results.extend(results)

            # Get next page URL (already includes params)
            next_url = response.get("next")
            if next_url:
                # Extract path from full URL for next request
                from urllib.parse import parse_qsl, urlparse

                parsed = urlparse(next_url)
                next_endpoint = self.relative_endpoint(parsed.path)
                next_params = dict(parse_qsl(parsed.query))
                if next_endpoint == endpoint and next_params == params:
                    # Defensive guard: identical next request means no forward
                    # progress; stop rather than loop indefinitely.
                    logger.warning(
                        "pagination_no_progress",
                        resource_type=resource_type,
                        endpoint=next_endpoint,
                    )
                    break
                endpoint = next_endpoint
                params = next_params
            else:
                endpoint = None

        logger.debug(
            "list_resources_completed",
            resource_type=resource_type,
            total_results=len(all_results),
            filters=filters,
        )

        return all_results

    async def validate_connectivity(self) -> bool:
        """Validate connectivity to AAP 2.6 instance.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            await self.get("ping/")
            logger.info("aap_connectivity_validated")
            return True
        except Exception as e:
            logger.error("aap_connectivity_failed", error=str(e))
            return False
