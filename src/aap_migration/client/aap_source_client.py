"""AAP 2.3 Source Client for extracting resources.

This client provides methods to extract all resource types from AAP 2.3
with efficient pagination and filtering.
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from aap_migration.client.api_layout import normalize_host_url
from aap_migration.client.base_client import BaseAPIClient
from aap_migration.config import AAPInstanceConfig
from aap_migration.resources import get_endpoint
from aap_migration.utils.logging import get_logger
from aap_migration.utils.retry import retry_api_call

logger = get_logger(__name__)


class AAPSourceClient(BaseAPIClient):
    """Client for AAP 2.3 source instance.

    This client extends BaseAPIClient with AAP-specific methods for
    extracting resources using pagination.
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
        """Initialize AAP source client.

        Args:
            config: AAP instance configuration
            rate_limit: Maximum requests per second
            log_payloads: Enable request/response payload logging
            max_payload_size: Maximum payload size to log before truncation
            max_connections: Maximum number of connections in pool
            max_keepalive_connections: Maximum keep-alive connections
        """
        if config.token is None:
            raise ValueError("API token must be resolved before initializing AAPSourceClient")
        if not config.version:
            raise ValueError(
                "SOURCE__VERSION must be set; source AAP version cannot be detected "
                "reliably from the API on older releases."
            )

        super().__init__(
            host_url=normalize_host_url(config.url, instance="source"),
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
        logger.info("aap_source_client_initialized", url=self.host_url, version=config.version)

    async def get_version(self) -> str:
        """Return the configured source AAP version."""
        return self.aap_version

    @retry_api_call
    async def get_paginated(
        self,
        endpoint: str,
        page_size: int = 200,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all pages from a paginated endpoint.

        Args:
            endpoint: API endpoint path
            page_size: Number of items per page (max 200)
            params: Additional query parameters

        Returns:
            List of all items from all pages
        """
        all_results: list[dict[str, Any]] = []
        page = 1
        query_params = params.copy() if params else {}
        query_params["page_size"] = min(page_size, 200)  # AAP max is 200

        while True:
            query_params["page"] = page

            logger.debug(
                "fetching_page",
                endpoint=endpoint,
                page=page,
                page_size=query_params["page_size"],
            )

            response = await self.get(endpoint, params=query_params)

            results = response.get("results", [])
            all_results.extend(results)

            count = response.get("count", 0)
            next_url = response.get("next")

            logger.info(
                "page_fetched",
                endpoint=endpoint,
                page=page,
                items_this_page=len(results),
                total_items_so_far=len(all_results),
                total_count=count,
            )

            # Break if no more pages
            if not next_url or len(results) == 0:
                break

            page += 1

        logger.info(
            "pagination_complete",
            endpoint=endpoint,
            total_pages=page,
            total_items=len(all_results),
        )

        return all_results

    async def get_count(self, endpoint: str) -> int:
        """Get total count of resources at an endpoint.

        Args:
            endpoint: API endpoint path

        Returns:
            Total count of resources
        """
        response = await self.get(endpoint, params={"page_size": 1})
        return response.get("count", 0)

    async def get_all_resources_parallel(
        self,
        endpoint: str,
        page_size: int = 200,
        max_concurrent: int = 5,
        **filters: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Fetch all resources with parallel page fetching.

        This method fetches multiple pages concurrently to improve performance.
        It respects resume filters (id__gt, order_by) for checkpoint resume support.

        Args:
            endpoint: API endpoint path
            page_size: Items per page (max 200)
            max_concurrent: Maximum concurrent page requests
            **filters: Additional query filters (e.g., id__gt, order_by for resume)

        Yields:
            Individual resources from all pages
        """
        # First, get total count (respects id__gt filter for resume)
        count_params = {"page_size": 1, **filters}
        response = await self.get(endpoint, params=count_params)
        total_count = response.get("count", 0)

        if total_count == 0:
            logger.info(
                "parallel_fetch_empty",
                endpoint=endpoint,
                filters=filters,
            )
            return

        page_size = min(page_size, 200)  # AAP max is 200
        total_pages = (total_count + page_size - 1) // page_size

        logger.info(
            "parallel_fetch_started",
            endpoint=endpoint,
            total_count=total_count,
            total_pages=total_pages,
            max_concurrent=max_concurrent,
            page_size=page_size,
            filters=filters if filters else None,
        )

        # Semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_page(page_num: int) -> tuple[int, list[dict[str, Any]]]:
            """Fetch a single page with semaphore control.

            Returns:
                Tuple of (page_num, results) to maintain order information
            """
            async with semaphore:
                params = {"page_size": page_size, "page": page_num, **filters}
                try:
                    page_response = await self.get(endpoint, params=params)
                    results = page_response.get("results", [])
                    logger.debug(
                        "parallel_page_fetched",
                        endpoint=endpoint,
                        page=page_num,
                        items=len(results),
                    )
                    return page_num, results
                except Exception as e:
                    logger.error(
                        "parallel_page_fetch_failed",
                        endpoint=endpoint,
                        page=page_num,
                        error=str(e),
                    )
                    raise

        # Fetch pages in batches to control memory
        # Process 2x concurrent pages at a time to keep pipeline full
        batch_size = max_concurrent * 2
        total_yielded = 0

        for batch_start in range(1, total_pages + 1, batch_size):
            batch_end = min(batch_start + batch_size, total_pages + 1)
            page_range = list(range(batch_start, batch_end))

            logger.debug(
                "parallel_fetch_batch",
                pages=page_range,
                batch_start=batch_start,
                batch_end=batch_end - 1,
            )

            # Fetch all pages in this batch concurrently
            tasks = [fetch_page(page_num) for page_num in page_range]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results in page order (important for consistent behavior)
            for page_num, result in zip(page_range, results, strict=False):
                if isinstance(result, Exception):
                    logger.error(
                        "parallel_page_failed",
                        page=page_num,
                        error=str(result),
                    )
                    # Re-raise to stop the export on error
                    raise result

                # result is (page_num, resources_list)
                _returned_page, resources = result
                for resource in resources:
                    yield resource
                    total_yielded += 1

        logger.info(
            "parallel_fetch_complete",
            endpoint=endpoint,
            total_pages=total_pages,
            total_items=total_yielded,
            expected_count=total_count,
        )

    # Organization resources
    @retry_api_call
    async def get_organizations(self, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Get all organizations.

        Args:
            params: Optional query parameters

        Returns:
            List of organizations
        """
        return await self.get_paginated("organizations/", params=params)

    # User and team resources
    @retry_api_call
    async def get_users(self, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Get all users.

        Args:
            params: Optional query parameters

        Returns:
            List of users
        """
        return await self.get_paginated("users/", params=params)

    @retry_api_call
    async def get_teams(self, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Get all teams.

        Args:
            params: Optional query parameters

        Returns:
            List of teams
        """
        return await self.get_paginated("teams/", params=params)

    # Credential resources
    @retry_api_call
    async def get_credential_types(
        self, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get all credential types.

        Args:
            params: Optional query parameters

        Returns:
            List of credential types
        """
        return await self.get_paginated("credential_types/", params=params)

    @retry_api_call
    async def get_credentials(self, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Get all credentials.

        Note: Encrypted fields will show as '$encrypted$' and cannot be extracted.

        Args:
            params: Optional query parameters

        Returns:
            List of credentials
        """
        return await self.get_paginated("credentials/", params=params)

    # Inventory resources
    @retry_api_call
    async def get_inventories(self, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Get all inventories.

        Args:
            params: Optional query parameters

        Returns:
            List of inventories
        """
        return await self.get_paginated("inventories/", params=params)

    @retry_api_call
    async def get_inventory_sources(
        self, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get all inventory sources.

        Args:
            params: Optional query parameters

        Returns:
            List of inventory sources
        """
        return await self.get_paginated("inventory_sources/", params=params)

    @retry_api_call
    async def get_hosts(
        self, inventory_id: int | None = None, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get hosts, optionally filtered by inventory.

        Args:
            inventory_id: Optional inventory ID to filter by
            params: Optional query parameters

        Returns:
            List of hosts
        """
        if inventory_id:
            endpoint = f"inventories/{inventory_id}/hosts/"
        else:
            endpoint = "hosts/"
        return await self.get_paginated(endpoint, params=params)

    @retry_api_call
    async def get_groups(
        self, inventory_id: int | None = None, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get groups, optionally filtered by inventory.

        Args:
            inventory_id: Optional inventory ID to filter by
            params: Optional query parameters

        Returns:
            List of groups
        """
        if inventory_id:
            endpoint = f"inventories/{inventory_id}/groups/"
        else:
            endpoint = "groups/"
        return await self.get_paginated(endpoint, params=params)

    # Project and execution environment resources
    @retry_api_call
    async def get_projects(self, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Get all projects.

        Args:
            params: Optional query parameters

        Returns:
            List of projects
        """
        return await self.get_paginated("projects/", params=params)

    @retry_api_call
    async def get_execution_environments(
        self, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get all execution environments.

        Args:
            params: Optional query parameters

        Returns:
            List of execution environments
        """
        return await self.get_paginated("execution_environments/", params=params)

    @retry_api_call
    async def get_instance_groups(
        self, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get all instance groups.

        Args:
            params: Optional query parameters

        Returns:
            List of instance groups
        """
        return await self.get_paginated("instance_groups/", params=params)

    # Job template resources
    @retry_api_call
    async def get_job_templates(self, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Get all job templates.

        Args:
            params: Optional query parameters

        Returns:
            List of job templates
        """
        return await self.get_paginated("job_templates/", params=params)

    @retry_api_call
    async def get_job_template_credentials(
        self, job_template_id: int, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get credentials for a specific job template.

        Args:
            job_template_id: Job template ID
            params: Optional query parameters

        Returns:
            List of credential references (id, name, kind)
        """
        endpoint = f"job_templates/{job_template_id}/credentials/"
        return await self.get_paginated(endpoint, params=params)

    @retry_api_call
    async def get_workflow_job_templates(
        self, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get all workflow job templates.

        Args:
            params: Optional query parameters

        Returns:
            List of workflow job templates
        """
        return await self.get_paginated("workflow_job_templates/", params=params)

    @retry_api_call
    async def get_workflow_nodes(
        self, workflow_id: int, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get workflow nodes for a specific workflow.

        Args:
            workflow_id: Workflow job template ID
            params: Optional query parameters

        Returns:
            List of workflow nodes
        """
        endpoint = f"workflow_job_templates/{workflow_id}/workflow_nodes/"
        return await self.get_paginated(endpoint, params=params)

    # Schedule resources
    @retry_api_call
    async def get_schedules(self, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Get all schedules.

        Args:
            params: Optional query parameters

        Returns:
            List of schedules
        """
        return await self.get_paginated("schedules/", params=params)

    # Notification resources
    @retry_api_call
    async def get_notification_templates(
        self, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get all notification templates.

        Args:
            params: Optional query parameters

        Returns:
            List of notification templates
        """
        return await self.get_paginated("notification_templates/", params=params)

    # Label resources
    @retry_api_call
    async def get_labels(self, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Get all labels.

        Args:
            params: Optional query parameters

        Returns:
            List of labels
        """
        return await self.get_paginated("labels/", params=params)

    # Role assignments
    @retry_api_call
    async def get_role_assignments(
        self, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get all role assignments.

        Args:
            params: Optional query parameters

        Returns:
            List of role assignments
        """
        return await self.get_paginated("role_user_assignments/", params=params)

    # Utility methods
    async def get_resource_by_id(self, resource_type: str, resource_id: int) -> dict[str, Any]:
        """Get a specific resource by ID.

        Args:
            resource_type: Resource type (e.g., 'inventories', 'hosts')
            resource_id: Resource ID

        Returns:
            Resource data
        """
        base = get_endpoint(resource_type).rstrip("/")
        endpoint = f"{base}/{resource_id}/"
        return await self.get(endpoint)

    async def search_resources(
        self,
        resource_type: str,
        search_query: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search for resources by name or other fields.

        Args:
            resource_type: Resource type (e.g., 'inventories', 'hosts')
            search_query: Search query string
            params: Additional query parameters

        Returns:
            List of matching resources
        """
        query_params = params.copy() if params else {}
        query_params["search"] = search_query
        endpoint = get_endpoint(resource_type)
        return await self.get_paginated(endpoint, params=query_params)
