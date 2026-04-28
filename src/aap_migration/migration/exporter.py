"""Resource exporters for extracting data from AAP 2.3.

This module provides a base exporter class and resource-specific exporters
that use generators for memory-efficient extraction of large datasets.
"""

import asyncio
import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from aap_migration.client.aap_source_client import AAPSourceClient
from aap_migration.client.exceptions import APIError
from aap_migration.config import PerformanceConfig, normalized_execution_environment_skip_names
from aap_migration.migration.state import MigrationState
from aap_migration.resources import get_endpoint
from aap_migration.utils.inventory_fk import parse_inventory_id_from_api_value
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


async def _fetch_template_survey_spec(
    client: AAPSourceClient,
    resource_type: str,
    template_id: int,
) -> dict[str, Any]:
    """GET ``{resource}/{id}/survey_spec/`` (empty ``{}`` when no survey questions).

    Stored on export as ``_survey_spec`` and POSTed after template create on import.
    """
    base = get_endpoint(resource_type).rstrip("/")
    endpoint = f"{base}/{template_id}/survey_spec/"
    try:
        resp = await client.get(endpoint)
        return resp if isinstance(resp, dict) else {}
    except Exception as e:
        logger.warning(
            "survey_spec_fetch_failed",
            resource_type=resource_type,
            template_id=template_id,
            error=str(e),
        )
        return {}


@runtime_checkable
class ExporterProtocol(Protocol):
    """Protocol defining the interface for resource exporters.

    All exporter classes must implement the export() method.
    """

    def export(self, **kwargs: Any) -> AsyncGenerator[dict[str, Any], None]:
        """Export resources.

        Args:
            **kwargs: Resource-specific keyword arguments

        Yields:
            Resource dictionaries
        """
        ...

    def export_parallel(
        self,
        resource_type: str,
        endpoint: str,
        page_size: int = 200,
        max_concurrent_pages: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export resources using parallel page fetching.

        Args:
            resource_type: Type of resource being exported
            endpoint: API endpoint to fetch from
            page_size: Number of items per page
            max_concurrent_pages: Maximum number of pages to fetch concurrently
            filters: Optional query parameters for filtering

        Yields:
            Individual resource dictionaries
        """
        ...

    def set_skip_dynamic_hosts(self, skip: bool) -> None:
        """Set whether to skip dynamic hosts during export.

        Args:
            skip: Whether to skip dynamic hosts
        """
        ...

    def set_skip_smart_inventories(self, skip: bool) -> None:
        """Set whether to skip smart inventories during export.

        Args:
            skip: Whether to skip smart inventories
        """
        ...

    def set_resume_checkpoint(self, resume_from_id: int | None) -> None:
        """Set the resume checkpoint for this exporter.

        Args:
            resume_from_id: Maximum source_id that was already exported
        """
        ...


class ResourceExporter:
    """Base class for exporting resources from AAP 2.3.

    Uses async generators to avoid loading all resources into memory.
    Integrates with state management for tracking progress.
    """

    def __init__(
        self,
        client: AAPSourceClient,
        state: MigrationState,
        performance_config: PerformanceConfig,
    ):
        """Initialize resource exporter.

        Args:
            client: AAP source client instance
            state: Migration state manager
            performance_config: Performance configuration
        """
        self.client = client
        self.state = state
        self.performance_config = performance_config
        self.stats = {
            "exported_count": 0,
            "error_count": 0,
            "skipped_count": 0,
        }

        # Cache for existing mappings (for efficient export resume)
        # Stores (resource_type, source_id) tuples for O(1) lookup
        self._existing_mappings_cache: set[tuple[str, int]] = set()
        self._cache_loaded_for: str | None = None  # Track which resource type is cached

        # Resume checkpoint: skip API calls for resources with id <= this value
        self._resume_from_id: int | None = None

        # Filtering flags (can be overridden by subclasses)
        self.skip_dynamic_hosts: bool = False
        self.skip_smart_inventories: bool = False

    def set_resume_checkpoint(self, resume_from_id: int | None) -> None:
        """Set the resume checkpoint for this exporter.

        When set, the exporter will skip API calls for resources with id <= resume_from_id
        by using ?id__gt=resume_from_id&order_by=id in the API query.

        Args:
            resume_from_id: Maximum source_id that was already exported (None to disable resume)
        """
        self._resume_from_id = resume_from_id
        if resume_from_id is not None:
            logger.info(
                "resume_checkpoint_set",
                resume_from_id=resume_from_id,
            )

    def _load_existing_mappings_cache(self, resource_type: str) -> None:
        """Pre-load all existing ID mappings for a resource type into memory.

        This eliminates N+1 query problem during export resume by loading all
        mappings once and performing O(1) set lookups instead of database queries.

        Args:
            resource_type: Type of resource to load mappings for
        """
        if self._cache_loaded_for == resource_type:
            return  # Already loaded for this resource type

        logger.info("loading_existing_mappings_cache", resource_type=resource_type)

        try:
            # Single database query to load all source IDs
            source_ids = self.state.get_all_source_ids(resource_type)
            self._existing_mappings_cache = {(resource_type, sid) for sid in source_ids}
            self._cache_loaded_for = resource_type

            logger.info(
                "existing_mappings_cache_loaded",
                resource_type=resource_type,
                count=len(self._existing_mappings_cache),
            )

        except Exception as e:
            logger.warning(
                "failed_to_load_mappings_cache",
                resource_type=resource_type,
                error=str(e),
            )
            # On failure, use empty cache (will check DB per resource as fallback)
            self._existing_mappings_cache = set()
            self._cache_loaded_for = resource_type

    async def get_count(self, endpoint: str, filters: dict[str, Any] | None = None) -> int:
        """Get total count of resources without fetching all data.

        Makes a single API call with page_size=1 to get the count field.
        Includes retry logic for server errors (500, 502, 503, 504).

        Args:
            endpoint: API endpoint to query
            filters: Optional query parameters for filtering

        Returns:
            Total count of resources
        """
        params = filters.copy() if filters else {}
        params["page_size"] = 1
        params["page"] = 1

        # Retry logic for server errors
        max_retries = 5
        retry_delay = 5.0  # Start with 5 seconds

        for attempt in range(max_retries):
            try:
                response = await self.client.get(endpoint, params=params)
                return response.get("count", 0)
            except APIError as e:
                # Retry on server errors (500, 502, 503, 504)
                if hasattr(e, "status_code") and e.status_code in (500, 502, 503, 504):
                    if attempt < max_retries - 1:
                        logger.warning(
                            "get_count_server_error_retry",
                            endpoint=endpoint,
                            attempt=attempt + 1,
                            max_retries=max_retries,
                            status_code=e.status_code,
                            retry_delay=retry_delay,
                            error=str(e),
                        )
                        await asyncio.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, 60)  # Exponential backoff, max 1 min
                        continue
                    else:
                        logger.error(
                            "get_count_server_error_exhausted",
                            endpoint=endpoint,
                            attempts=max_retries,
                            error=str(e),
                        )
                        return 0
                else:
                    logger.error(
                        "get_count_error",
                        endpoint=endpoint,
                        error=str(e),
                    )
                    return 0
            except Exception as e:
                logger.error(
                    "get_count_error",
                    endpoint=endpoint,
                    error=str(e),
                )
                return 0

        return 0

    async def export_resources(
        self,
        resource_type: str,
        endpoint: str,
        page_size: int = 100,
        filters: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export resources using pagination with generator pattern.

        Args:
            resource_type: Type of resource being exported (for logging)
            endpoint: API endpoint to fetch from
            page_size: Number of items per page
            filters: Optional query parameters for filtering

        Yields:
            Individual resource dictionaries

        Note:
            If set_resume_checkpoint() was called, this will apply id__gt filtering
            to skip already-exported resources at the API level.
        """
        page = 1
        params = filters.copy() if filters else {}
        params["page_size"] = min(page_size, 200)  # AAP max is 200

        # Apply ID filtering for true checkpoint resume
        if self._resume_from_id is not None:
            params["id__gt"] = self._resume_from_id
            params["order_by"] = "id"
            logger.info(
                "export_resuming_from_checkpoint",
                resource_type=resource_type,
                resume_from_id=self._resume_from_id,
            )

        logger.info(
            "export_started",
            resource_type=resource_type,
            endpoint=endpoint,
            filters=filters,
            resume_from_id=self._resume_from_id,
        )

        # Load existing mappings cache ONCE before starting export
        # This enables efficient O(1) resume checks instead of N database queries
        self._load_existing_mappings_cache(resource_type)

        total_fetched = 0
        export_stopped_early = False

        while True:
            params["page"] = page

            # Retry logic for server errors (502, 503, 504)
            max_retries = 5
            retry_delay = 5.0  # Start with 5 seconds

            # Initialize variables before retry loop (for type safety)
            results: list[dict[str, Any]] = []
            next_url: str | None = None

            for attempt in range(max_retries):
                try:
                    response = await self.client.get(endpoint, params=params)

                    results = response.get("results", [])
                    count = response.get("count", 0)
                    next_url = response.get("next")

                    logger.debug(
                        "export_page_fetched",
                        resource_type=resource_type,
                        page=page,
                        items_this_page=len(results),
                        total_count=count,
                    )

                    # Yield each resource individually
                    for resource in results:
                        processed = await self._process_resource(resource, resource_type)
                        if processed:
                            # Check if resource is marked as skipped
                            if processed.get("_skipped"):
                                self.stats["skipped_count"] += 1
                                yield processed
                            else:
                                self.stats["exported_count"] += 1
                                total_fetched += 1
                                yield processed

                    # Note: No artificial delay needed - rate limiting is handled by
                    # BaseAPIClient semaphore. Parallel export (export_parallel) is
                    # the preferred method for performance.

                    # Break retry loop on success
                    break

                except APIError as e:
                    # Retry on server errors (502, 503, 504)
                    if hasattr(e, "status_code") and e.status_code in (502, 503, 504):
                        if attempt < max_retries - 1:
                            logger.warning(
                                "export_page_server_error_retry",
                                resource_type=resource_type,
                                page=page,
                                attempt=attempt + 1,
                                max_retries=max_retries,
                                status_code=e.status_code,
                                retry_delay=retry_delay,
                                error=str(e),
                            )
                            await asyncio.sleep(retry_delay)
                            retry_delay = min(
                                retry_delay * 2, 120
                            )  # Exponential backoff, max 2 min
                            continue
                        else:
                            # Retries exhausted - stop gracefully instead of crashing
                            logger.error(
                                "export_page_server_error_exhausted",
                                resource_type=resource_type,
                                page=page,
                                attempts=max_retries,
                                total_exported_so_far=total_fetched,
                                error=str(e),
                            )
                            self.stats["error_count"] += 1
                            export_stopped_early = True
                            break  # Exit retry loop, will stop export
                    else:
                        # Non-retryable API error - stop gracefully
                        logger.error(
                            "export_page_error",
                            resource_type=resource_type,
                            page=page,
                            total_exported_so_far=total_fetched,
                            error=str(e),
                        )
                        self.stats["error_count"] += 1
                        export_stopped_early = True
                        break  # Exit retry loop, will stop export

                except Exception as e:
                    logger.error(
                        "export_page_error",
                        resource_type=resource_type,
                        page=page,
                        total_exported_so_far=total_fetched,
                        error=str(e),
                    )
                    self.stats["error_count"] += 1
                    export_stopped_early = True
                    break  # Exit retry loop, will stop export

            # Stop export if we hit an unrecoverable error
            if export_stopped_early:
                logger.warning(
                    "export_stopped_early",
                    resource_type=resource_type,
                    page=page,
                    total_exported=total_fetched,
                    reason="Server errors exhausted retries. Resume by re-running export command.",
                )
                break

            # Break if no more pages
            if not next_url or len(results) == 0:
                break

            page += 1

        if export_stopped_early:
            logger.warning(
                "export_partial_completion",
                resource_type=resource_type,
                total_pages_fetched=page,
                total_exported=total_fetched,
                stats=self.stats,
                message="Export stopped due to server errors. Re-run command to resume from where it left off.",
            )
        else:
            logger.info(
                "export_completed",
                resource_type=resource_type,
                total_pages=page,
                total_exported=total_fetched,
                stats=self.stats,
            )

    async def _process_resource(
        self, resource: dict[str, Any], resource_type: str
    ) -> dict[str, Any] | None:
        """Process and validate a resource before yielding.

        Subclasses can override to add custom processing.

        Args:
            resource: Raw resource data from API
            resource_type: Type of resource

        Returns:
            Processed resource or None if should be skipped
        """
        # Basic validation - ensure required fields exist
        if not resource.get("id"):
            logger.warning(
                "resource_missing_id",
                resource_type=resource_type,
                resource=resource,
            )
            self.stats["skipped_count"] += 1
            return None

        # Only skip previously-exported resources when explicitly resuming
        if self._resume_from_id is not None:
            if (resource_type, resource["id"]) in self._existing_mappings_cache:
                logger.debug(
                    "resource_already_exported",
                    resource_type=resource_type,
                    source_id=resource["id"],
                )
                self.stats["skipped_count"] += 1
                return None

        return resource

    async def export_parallel(
        self,
        resource_type: str,
        endpoint: str,
        page_size: int = 200,
        max_concurrent_pages: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export resources using parallel page fetching for improved performance.

        This method fetches multiple pages concurrently, providing 3-5x faster
        API operations compared to sequential fetching.

        Supports resume via id__gt filter - if set_resume_checkpoint() was called,
        all pages within the filtered subset can be fetched concurrently.

        Args:
            resource_type: Type of resource being exported (for logging)
            endpoint: API endpoint to fetch from
            page_size: Number of items per page (max 200)
            max_concurrent_pages: Maximum number of pages to fetch concurrently
            filters: Optional query parameters for filtering

        Yields:
            Individual resource dictionaries
        """
        params = filters.copy() if filters else {}

        # Apply resource-specific filtering based on instance flags
        # This ensures filters work regardless of whether export() or export_parallel() is called
        if (
            resource_type == "hosts"
            and hasattr(self, "skip_dynamic_hosts")
            and self.skip_dynamic_hosts
        ):
            params["inventory_sources__isnull"] = "true"
            logger.info(
                "export_parallel_applying_dynamic_host_filter",
                message="API filter: inventory_sources__isnull=true (exclude dynamic hosts)",
            )

        if resource_type == "inventories":
            params["pending_deletion"] = "false"
            logger.info(
                "export_parallel_applying_inventory_filter",
                message="API filter: pending_deletion=false (exclude deleted inventories)",
            )

        if resource_type == "role_definitions":
            params["managed"] = "false"
            logger.info(
                "export_parallel_applying_role_definition_filter",
                message="API filter: managed=false (exclude built-in managed role definitions)",
            )

        # Apply ID filtering for true checkpoint resume
        if self._resume_from_id is not None:
            params["id__gt"] = self._resume_from_id
            params["order_by"] = "id"
            logger.info(
                "parallel_export_resuming_from_checkpoint",
                resource_type=resource_type,
                resume_from_id=self._resume_from_id,
            )

        logger.info(
            "parallel_export_started",
            resource_type=resource_type,
            endpoint=endpoint,
            max_concurrent_pages=max_concurrent_pages,
            page_size=page_size,
            resume_from_id=self._resume_from_id,
            filters=filters,
        )

        # Load existing mappings cache ONCE before starting export (if resuming)
        if self._resume_from_id is not None:
            self._load_existing_mappings_cache(resource_type)

        total_fetched = 0

        try:
            async for resource in self.client.get_all_resources_parallel(
                endpoint,
                page_size=min(page_size, 200),
                max_concurrent=max_concurrent_pages,
                **params,
            ):
                processed = await self._process_resource(resource, resource_type)
                if processed:
                    # Check if resource is marked as skipped
                    if processed.get("_skipped"):
                        self.stats["skipped_count"] += 1
                        yield processed
                    else:
                        self.stats["exported_count"] += 1
                        total_fetched += 1
                        yield processed

        except Exception as e:
            logger.error(
                "parallel_export_failed",
                resource_type=resource_type,
                endpoint=endpoint,
                total_exported_so_far=total_fetched,
                error=str(e),
            )
            self.stats["error_count"] += 1
            raise

        logger.info(
            "parallel_export_completed",
            resource_type=resource_type,
            total_exported=total_fetched,
            stats=self.stats,
        )

    def get_stats(self) -> dict[str, int]:
        """Get export statistics.

        Returns:
            Dictionary with export statistics
        """
        return self.stats.copy()

    def reset_stats(self) -> None:
        """Reset export statistics."""
        self.stats = {
            "exported_count": 0,
            "error_count": 0,
            "skipped_count": 0,
        }


class LabelExporter(ResourceExporter):
    """Exporter for label resources."""

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export labels.

        Args:
            filters: Optional query parameters for filtering

        Yields:
            Label dictionaries
        """
        logger.info("exporting_labels")
        async for label in self.export_resources(
            resource_type="labels",
            endpoint="labels/",
            page_size=self.performance_config.batch_sizes.get("labels", 200),
            filters=filters,
        ):
            yield label


class CredentialTypeExporter(ResourceExporter):
    """Exporter for credential type resources."""

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export credential types (custom types only).

        Note: Only exports custom (non-managed) credential types.
        Built-in credential types are skipped as they exist in AAP 2.6.

        Args:
            filters: Optional query parameters for filtering

        Yields:
            Credential type dictionaries (custom types only)
        """
        logger.info("exporting_credential_types")
        async for cred_type in self.export_resources(
            resource_type="credential_types",
            endpoint="credential_types/",
            page_size=self.performance_config.batch_sizes.get("credential_types", 200),
            filters=filters,
        ):
            yield cred_type

    async def _process_resource(
        self, resource: dict[str, Any], resource_type: str
    ) -> dict[str, Any] | None:
        """Process credential type resource, including managed types.

        Args:
            resource: Raw resource data from API
            resource_type: Type of resource

        Returns:
            Processed resource or None if should be skipped

        Note:
            Managed (built-in) credential types are included in export so their
            IDs can be mapped during import. They will be mapped by name to
            target IDs during import, not created.
        """
        # Log managed types for visibility, but include them in export
        if resource.get("managed", False):
            logger.debug(
                "exporting_managed_credential_type",
                credential_type_id=resource.get("id"),
                name=resource.get("name"),
                message="Managed type will be mapped by name during import",
            )

        # Call parent processing for all types (managed and custom)
        return await super()._process_resource(resource, resource_type)


class OrganizationExporter(ResourceExporter):
    """Exporter for organization resources."""

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export organizations.

        Args:
            filters: Optional query parameters for filtering

        Yields:
            Organization dictionaries
        """
        logger.info("exporting_organizations")
        async for org in self.export_resources(
            resource_type="organizations",
            endpoint="organizations/",
            page_size=self.performance_config.batch_sizes.get("organizations", 200),
            filters=filters,
        ):
            yield org


class InventoryExporter(ResourceExporter):
    """Exporter for inventory resources."""

    def __init__(
        self,
        client: AAPSourceClient,
        state: MigrationState,
        performance_config: PerformanceConfig,
    ):
        """Initialize inventory exporter with inventory sources cache.

        Args:
            client: AAP source client instance
            state: Migration state manager
            performance_config: Performance configuration
        """
        super().__init__(client, state, performance_config)
        self._inventory_sources_cache: dict[int, list[dict[str, Any]]] = {}
        self._cache_loaded = False

    def set_skip_smart_inventories(self, skip: bool) -> None:
        """Set whether to skip smart inventories during export.

        Args:
            skip: If True, only export static inventories (kind="")
        """
        self.skip_smart_inventories = skip
        if skip:
            logger.info(
                "skip_smart_inventories_enabled",
                message="Will skip smart inventories (kind='smart'), only export static inventories",
            )

    async def _load_inventory_sources_cache(self) -> None:
        """Pre-fetch all inventory sources into cache.

        This eliminates N+1 query pattern by loading all inventory sources
        once upfront instead of fetching each one individually per inventory.
        """
        if self._cache_loaded:
            return

        logger.info("loading_inventory_sources_cache")
        page = 1
        total_loaded = 0

        while True:
            try:
                response = await self.client.get(
                    "inventory_sources/", params={"page": page, "page_size": 200}
                )
                results = response.get("results", [])

                for source in results:
                    inventory_id = source.get("inventory")
                    if inventory_id:
                        if inventory_id not in self._inventory_sources_cache:
                            self._inventory_sources_cache[inventory_id] = []
                        self._inventory_sources_cache[inventory_id].append(source)
                        total_loaded += 1

                if not response.get("next") or len(results) == 0:
                    break

                page += 1

            except Exception as e:
                logger.error(
                    "failed_to_load_inventory_sources_cache",
                    page=page,
                    error=str(e),
                )
                # Continue with partial cache rather than failing
                break

        logger.info(
            "inventory_sources_cache_loaded",
            count=total_loaded,
            inventories_with_sources=len(self._inventory_sources_cache),
            pages_fetched=page,
        )
        self._cache_loaded = True

    async def _fetch_constructed_input_inventory_ids(self, constructed_inventory_id: int) -> list[int]:
        """GET ``inventories/<id>/input_inventories/`` and return input inventory PKs in order.

        The inventory list/detail response does not include a top-level ``input_inventories``
        array—only ``related.input_inventories``—so we sub-fetch for migration.
        """
        endpoint = f"inventories/{constructed_inventory_id}/input_inventories/"
        try:
            rows = await self.client.get_paginated(endpoint, page_size=200)
        except Exception as e:
            logger.warning(
                "constructed_inventory_input_inventories_fetch_failed",
                constructed_inventory_id=constructed_inventory_id,
                error=str(e),
            )
            return []
        out: list[int] = []
        for row in rows:
            rid = parse_inventory_id_from_api_value(row)
            if rid is not None:
                out.append(rid)
        return out

    async def export(
        self,
        filters: dict[str, Any] | None = None,
        include_sources: bool = True,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export inventories with optional inventory sources.

        Args:
            filters: Optional query parameters for filtering
            include_sources: Whether to fetch inventory sources for each inventory

        Yields:
            Inventory dictionaries with optional ``sources`` field and, for
            ``kind=constructed``, ``input_inventories`` (source inventory PKs from
            the input_inventories sub-list endpoint).
        """
        logger.info("exporting_inventories", include_sources=include_sources)

        # Pre-load inventory sources cache to avoid N+1 queries
        if include_sources:
            await self._load_inventory_sources_cache()

        # Apply inventory filtering - exclude deleted inventories
        if filters is None:
            filters = {}
        filters["pending_deletion"] = "false"
        logger.info(
            "applying_inventory_filter",
            message="API filter: pending_deletion=false (exclude deleted inventories)",
        )

        async for inventory in self.export_resources(
            resource_type="inventory",
            endpoint="inventories/",
            page_size=self.performance_config.batch_sizes.get("inventory", 100),
            filters=filters,
        ):
            # Optionally add inventory sources from cache
            if include_sources:
                inventory_id = inventory["id"]
                inventory["sources"] = self._inventory_sources_cache.get(inventory_id, [])

            # Constructed inventories: input inventory IDs live under related.input_inventories only;
            # fetch sub-resource so export JSON matches what import needs (top-level input_inventories).
            if (inventory.get("kind") or "") == "constructed":
                cid = inventory["id"]
                input_ids = await self._fetch_constructed_input_inventory_ids(cid)
                if input_ids:
                    inventory["input_inventories"] = input_ids
                    logger.info(
                        "constructed_inventory_input_inventories_attached",
                        constructed_inventory_id=cid,
                        input_inventory_source_ids=input_ids,
                    )
                else:
                    logger.warning(
                        "constructed_inventory_input_inventories_empty_after_fetch",
                        constructed_inventory_id=cid,
                        message="Sub-list returned no input inventory PKs; UI input list will not migrate",
                    )

            yield inventory

    async def export_parallel(
        self,
        resource_type: str,
        endpoint: str,
        page_size: int = 200,
        max_concurrent_pages: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Parallel fetch with the same enrichment as :meth:`export` (sources cache + constructed inputs).

        The CLI uses this for inventory export; the base implementation only yields raw list rows.
        """
        await self._load_inventory_sources_cache()

        async for inventory in super().export_parallel(
            resource_type=resource_type,
            endpoint=endpoint,
            page_size=page_size,
            max_concurrent_pages=max_concurrent_pages,
            filters=filters,
        ):
            inventory_id = inventory["id"]
            inventory["sources"] = self._inventory_sources_cache.get(inventory_id, [])

            if (inventory.get("kind") or "") == "constructed":
                cid = int(inventory["id"])
                input_ids = await self._fetch_constructed_input_inventory_ids(cid)
                if input_ids:
                    inventory["input_inventories"] = input_ids
                    logger.info(
                        "constructed_inventory_input_inventories_attached",
                        constructed_inventory_id=cid,
                        input_inventory_source_ids=input_ids,
                    )
                else:
                    logger.warning(
                        "constructed_inventory_input_inventories_empty_after_fetch",
                        constructed_inventory_id=cid,
                        message="Sub-list returned no input inventory PKs; UI input list will not migrate",
                    )

            yield inventory


class InventoryGroupExporter(ResourceExporter):
    """Exporter for inventory group resources.

    Inventory groups can have nested hierarchies (parent-child relationships).
    """

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export inventory groups.

        Groups may have parent-child relationships indicated by the 'children' field.
        Group variables are stored as JSON strings and must be preserved.

        Args:
            filters: Optional query parameters for filtering

        Yields:
            Inventory group dictionaries
        """
        logger.info("exporting_inventory_groups")
        async for group in self.export_resources(
            resource_type="groups",
            endpoint="groups/",
            page_size=self.performance_config.batch_sizes.get("groups", 100),
            filters=filters,
        ):
            yield group


class InventorySourceExporter(ResourceExporter):
    """Exporter for inventory source resources.

    Inventory sources define how inventory data is synchronized from
    external sources (cloud providers, SCM, etc.).
    """

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export inventory sources.

        Args:
            filters: Optional query parameters for filtering

        Yields:
            Inventory source dictionaries
        """
        logger.info("exporting_inventory_sources")
        async for source in self.export_resources(
            resource_type="inventory_sources",
            endpoint="inventory_sources/",
            page_size=self.performance_config.batch_sizes.get("inventory_sources", 200),
            filters=filters,
        ):
            yield source


class HostExporter(ResourceExporter):
    """Exporter for host resources."""

    def __init__(
        self,
        client: AAPSourceClient,
        state: MigrationState,
        performance_config: PerformanceConfig,
    ):
        """Initialize host exporter with dynamic host filtering option."""
        super().__init__(client, state, performance_config)

    def set_skip_dynamic_hosts(self, skip: bool) -> None:
        """Set whether to skip hosts from dynamic inventory sources.

        Args:
            skip: If True, only export static hosts (has_inventory_sources=False)
        """
        self.skip_dynamic_hosts = skip
        if skip:
            logger.info(
                "skip_dynamic_hosts_enabled",
                message="Will skip hosts from dynamic inventory sources",
            )

    async def export(
        self,
        inventory_id: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export hosts, optionally filtered by inventory.

        Args:
            inventory_id: Optional inventory ID to filter by
            filters: Optional query parameters for filtering

        Yields:
            Host dictionaries
        """
        # Apply host filtering if enabled
        if filters is None:
            filters = {}
        if self.skip_dynamic_hosts:
            # API-level filtering: only export static hosts (not from dynamic inventory sources)
            filters["inventory_sources__isnull"] = "true"
            logger.info(
                "applying_dynamic_host_filter",
                message="API filter: inventory_sources__isnull=true (exclude dynamic hosts)",
            )

        if inventory_id:
            logger.info("exporting_hosts_for_inventory", inventory_id=inventory_id)
            endpoint = f"inventories/{inventory_id}/hosts/"
        else:
            logger.info("exporting_all_hosts")
            endpoint = "hosts/"

        async for host in self.export_resources(
            resource_type="hosts",
            endpoint=endpoint,
            page_size=self.performance_config.batch_sizes.get("hosts", 200),
            filters=filters,
        ):
            yield host

    async def export_by_inventory(
        self, inventory_ids: list[int]
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export hosts for multiple inventories sequentially.

        Args:
            inventory_ids: List of inventory IDs

        Yields:
            Host dictionaries with 'inventory_id' field added
        """
        for inventory_id in inventory_ids:
            async for host in self.export(inventory_id=inventory_id):
                # Ensure inventory_id is in the host data
                host["inventory_id"] = inventory_id
                yield host


class CredentialExporter(ResourceExporter):
    """Exporter for credential resources."""

    def __init__(
        self,
        client: AAPSourceClient,
        state: MigrationState,
        performance_config: PerformanceConfig,
    ):
        """Initialize credential exporter with credential type cache.

        Args:
            client: AAP source client instance
            state: Migration state manager
            performance_config: Performance configuration
        """
        super().__init__(client, state, performance_config)
        self._credential_type_cache: dict[int, dict[str, Any]] = {}
        self._cache_loaded = False

    async def _load_credential_type_cache(self) -> None:
        """Pre-fetch all credential types into cache.

        This eliminates N+1 query pattern by loading all credential types
        once upfront instead of fetching each one individually per credential.
        """
        if self._cache_loaded:
            return

        logger.info("loading_credential_type_cache")
        page = 1
        total_loaded = 0

        while True:
            try:
                response = await self.client.get(
                    "credential_types/", params={"page": page, "page_size": 200}
                )
                results = response.get("results", [])

                for cred_type in results:
                    self._credential_type_cache[cred_type["id"]] = cred_type
                    total_loaded += 1

                if not response.get("next") or len(results) == 0:
                    break

                page += 1

            except Exception as e:
                logger.error(
                    "failed_to_load_credential_type_cache",
                    page=page,
                    error=str(e),
                )
                # Continue with partial cache rather than failing
                break

        logger.info(
            "credential_type_cache_loaded",
            count=total_loaded,
            pages_fetched=page,
        )
        self._cache_loaded = True

    async def export(
        self,
        filters: dict[str, Any] | None = None,
        include_types: bool = True,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export credentials.

        Note: Encrypted fields will appear as '$encrypted$' and cannot be extracted.

        Args:
            filters: Optional query parameters for filtering
            include_types: Whether to fetch credential type details

        Yields:
            Credential dictionaries with optional 'credential_type_details' field
        """
        logger.info("exporting_credentials", include_types=include_types)

        # Pre-load credential type cache to avoid N+1 queries
        if include_types:
            await self._load_credential_type_cache()

        async for credential in self.export_resources(
            resource_type="credentials",
            endpoint="credentials/",
            page_size=self.performance_config.batch_sizes.get("credentials", 50),
            filters=filters,
        ):
            # Mark encrypted fields
            if "inputs" in credential:
                for key, value in credential["inputs"].items():
                    if value == "$encrypted$":
                        credential.setdefault("_encrypted_fields", []).append(key)

            # Optionally add credential type details from cache
            if include_types and credential.get("credential_type"):
                cred_type_id = credential["credential_type"]
                if cred_type_id in self._credential_type_cache:
                    credential["credential_type_details"] = self._credential_type_cache[
                        cred_type_id
                    ]
                else:
                    logger.warning(
                        "credential_type_not_in_cache",
                        credential_id=credential["id"],
                        credential_type_id=cred_type_id,
                    )

            yield credential


class CredentialInputSourceExporter(ResourceExporter):
    """Exporter for credential input source resources.

    Credential input sources link credentials to external secret management systems
    like CyberArk, HashiCorp Vault, Azure Key Vault, etc.
    """

    def __init__(
        self,
        client: AAPSourceClient,
        state: MigrationState,
        performance_config: PerformanceConfig,
    ):
        """Initialize credential input source exporter with caches.

        Args:
            client: AAP source client instance
            state: Migration state manager
            performance_config: Performance configuration
        """
        super().__init__(client, state, performance_config)
        self._credential_cache: dict[int, dict[str, Any]] = {}
        self._credential_type_cache: dict[int, dict[str, Any]] = {}
        self._cache_loaded = False

    async def _load_caches(self) -> None:
        """Pre-fetch all credentials and credential types into cache.

        This eliminates N+1 query pattern for looking up credential details.
        """
        if self._cache_loaded:
            return

        logger.info("loading_credential_and_type_caches")

        # Load credential types first
        page = 1
        total_types = 0
        while True:
            try:
                response = await self.client.get(
                    "credential_types/", params={"page": page, "page_size": 200}
                )
                results = response.get("results", [])

                for cred_type in results:
                    self._credential_type_cache[cred_type["id"]] = cred_type
                    total_types += 1

                if not response.get("next") or len(results) == 0:
                    break

                page += 1

            except Exception as e:
                logger.error(
                    "failed_to_load_credential_type_cache",
                    page=page,
                    error=str(e),
                )
                break

        # Load credentials
        page = 1
        total_creds = 0
        while True:
            try:
                response = await self.client.get(
                    "credentials/", params={"page": page, "page_size": 200}
                )
                results = response.get("results", [])

                for cred in results:
                    self._credential_cache[cred["id"]] = cred
                    total_creds += 1

                if not response.get("next") or len(results) == 0:
                    break

                page += 1

            except Exception as e:
                logger.error(
                    "failed_to_load_credential_cache",
                    page=page,
                    error=str(e),
                )
                break

        logger.info(
            "caches_loaded",
            credential_types=total_types,
            credentials=total_creds,
        )
        self._cache_loaded = True

    async def export(
        self,
        filters: dict[str, Any] | None = None,
        include_details: bool = True,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export credential input sources.

        Credential input sources are used for external credential lookups
        from systems like CyberArk, HashiCorp Vault, Azure Key Vault, etc.

        Args:
            filters: Optional query parameters for filtering
            include_details: Whether to fetch credential and type details

        Yields:
            Credential input source dictionaries with optional details
        """
        logger.info("exporting_credential_input_sources", include_details=include_details)

        # Pre-load caches to avoid N+1 queries
        if include_details:
            await self._load_caches()

        async for input_source in self.export_resources(
            resource_type="credential_input_sources",
            endpoint="credential_input_sources/",
            page_size=self.performance_config.batch_sizes.get("credential_input_sources", 100),
            filters=filters,
        ):
            # Optionally add credential and credential type details from cache
            if include_details:
                # Add target credential details
                target_cred_id = input_source.get("target_credential")
                if target_cred_id and target_cred_id in self._credential_cache:
                    input_source["target_credential_details"] = self._credential_cache[
                        target_cred_id
                    ]

                # Add source credential details
                source_cred_id = input_source.get("source_credential")
                if source_cred_id and source_cred_id in self._credential_cache:
                    input_source["source_credential_details"] = self._credential_cache[
                        source_cred_id
                    ]

                    # Add source credential type details
                    source_cred = self._credential_cache[source_cred_id]
                    source_cred_type_id = source_cred.get("credential_type")
                    if source_cred_type_id and source_cred_type_id in self._credential_type_cache:
                        input_source["source_credential_type_details"] = (
                            self._credential_type_cache[source_cred_type_id]
                        )

            yield input_source


class ProjectExporter(ResourceExporter):
    """Exporter for project resources."""

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export projects.

        Args:
            filters: Optional query parameters for filtering

        Yields:
            Project dictionaries
        """
        logger.info("exporting_projects")
        async for project in self.export_resources(
            resource_type="projects",
            endpoint="projects/",
            page_size=self.performance_config.batch_sizes.get("projects", 50),
            filters=filters,
        ):
            yield project


class JobTemplateExporter(ResourceExporter):
    """Exporter for job template resources."""

    async def export(
        self,
        filters: dict[str, Any] | None = None,
        include_credentials: bool = True,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export job templates with credentials.

        Args:
            filters: Optional query parameters for filtering
            include_credentials: Whether to fetch credentials for each template

        Yields:
            Job template dictionaries with optional ``_credentials`` and ``_survey_spec``
        """
        logger.info("exporting_job_templates", include_credentials=include_credentials)
        async for template in self.export_resources(
            resource_type="job_templates",
            endpoint="job_templates/",
            page_size=self.performance_config.batch_sizes.get("job_templates", 100),
            filters=filters,
        ):
            # Optionally fetch job template credentials
            if include_credentials:
                # Optimization: Try to get credentials from summary_fields first
                # This avoids N+1 API calls for every job template
                summary_creds = template.get("summary_fields", {}).get("credentials")

                if summary_creds is not None:
                    template["_credentials"] = [cred["id"] for cred in summary_creds]
                    logger.debug(
                        "job_template_credentials_extracted_from_summary",
                        job_template_id=template["id"],
                        credential_count=len(template["_credentials"]),
                    )
                else:
                    # Fallback: Fetch from API if summary_fields missing
                    try:
                        credentials = await self.client.get_job_template_credentials(template["id"])
                        # Store credential IDs for import (only need IDs)
                        template["_credentials"] = [cred["id"] for cred in credentials]
                        logger.debug(
                            "job_template_credentials_fetched_from_api",
                            job_template_id=template["id"],
                            credential_count=len(credentials),
                        )
                    except Exception as e:
                        logger.warning(
                            "failed_to_fetch_job_template_credentials",
                            job_template_id=template["id"],
                            error=str(e),
                        )
                        template["_credentials"] = []

            template["_survey_spec"] = await _fetch_template_survey_spec(
                self.client, "job_templates", template["id"]
            )

            yield template

    async def export_parallel(
        self,
        resource_type: str,
        endpoint: str,
        page_size: int = 200,
        max_concurrent_pages: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export job templates with credentials using parallel fetching.

        Overrides base method to add credential fetching for each template.
        """
        async for template in super().export_parallel(
            resource_type=resource_type,
            endpoint=endpoint,
            page_size=page_size,
            max_concurrent_pages=max_concurrent_pages,
            filters=filters,
        ):
            # Fetch credentials for this job template
            # Optimization: Try to get credentials from summary_fields first
            summary_creds = template.get("summary_fields", {}).get("credentials")

            if summary_creds is not None:
                template["_credentials"] = [cred["id"] for cred in summary_creds]
                logger.debug(
                    "job_template_credentials_extracted_from_summary",
                    job_template_id=template["id"],
                    credential_count=len(template["_credentials"]),
                )
            else:
                # Fallback: Fetch from API
                try:
                    credentials = await self.client.get_job_template_credentials(template["id"])
                    template["_credentials"] = [cred["id"] for cred in credentials]
                    logger.debug(
                        "job_template_credentials_fetched_from_api",
                        job_template_id=template["id"],
                        credential_count=len(credentials),
                    )
                except Exception as e:
                    logger.warning(
                        "failed_to_fetch_job_template_credentials",
                        job_template_id=template["id"],
                        error=str(e),
                    )
                    template["_credentials"] = []

            template["_survey_spec"] = await _fetch_template_survey_spec(
                self.client, "job_templates", template["id"]
            )

            yield template


class WorkflowExporter(ResourceExporter):
    """Exporter for workflow job template resources."""

    @staticmethod
    def _endpoint_from_related_url(url: str | None) -> str | None:
        """Convert related URL to client endpoint path (without API prefix)."""
        if not url or not isinstance(url, str):
            return None
        marker = "/api/controller/v2/"
        if marker in url:
            return url.split(marker, 1)[1]
        cleaned = url.lstrip("/")
        if cleaned.startswith("api/controller/v2/"):
            return cleaned[len("api/controller/v2/") :]
        return cleaned

    async def _attach_workflow_approval_template_data(
        self, nodes: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Attach approval template payloads for approval nodes.

        Workflow approval templates are separate resources and must be created
        before node linking on import. We capture minimal fields needed for that.
        """
        for node in nodes:
            summary = node.get("summary_fields") or {}
            ujt = summary.get("unified_job_template") or {}
            if (ujt.get("unified_job_type") or "") != "workflow_approval":
                continue

            approval_data: dict[str, Any] = {
                "id": ujt.get("id") or node.get("unified_job_template"),
                "name": ujt.get("name"),
                "description": ujt.get("description", ""),
                "timeout": ujt.get("timeout", 0),
            }

            endpoint = self._endpoint_from_related_url(
                (node.get("related") or {}).get("unified_job_template")
            )
            if endpoint:
                try:
                    details = await self.client.get(endpoint)
                    approval_data.update(
                        {
                            "id": details.get("id", approval_data.get("id")),
                            "name": details.get("name", approval_data.get("name")),
                            "description": details.get(
                                "description", approval_data.get("description", "")
                            ),
                            "timeout": details.get("timeout", approval_data.get("timeout", 0)),
                        }
                    )
                except Exception as e:
                    logger.warning(
                        "workflow_approval_template_detail_fetch_failed",
                        endpoint=endpoint,
                        node_id=node.get("id"),
                        error=str(e),
                    )

            node["_approval_template"] = approval_data

        return nodes

    async def export(
        self,
        filters: dict[str, Any] | None = None,
        include_nodes: bool = True,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export workflow job templates with nodes.

        Args:
            filters: Optional query parameters for filtering
            include_nodes: Whether to fetch workflow nodes for each workflow

        Yields:
            Workflow job template dictionaries with optional 'nodes' field
        """
        logger.info("exporting_workflows", include_nodes=include_nodes)

        async for workflow in self.export_resources(
            resource_type="workflow_job_templates",
            endpoint="workflow_job_templates/",
            page_size=self.performance_config.batch_sizes.get("workflow_job_templates", 200),
            filters=filters,
        ):
            # Optionally fetch workflow nodes
            if include_nodes:
                try:
                    nodes = await self.client.get_workflow_nodes(workflow["id"])
                    nodes = await self._attach_workflow_approval_template_data(nodes)
                    workflow["nodes"] = nodes
                    logger.debug(
                        "workflow_nodes_fetched",
                        workflow_id=workflow["id"],
                        node_count=len(nodes),
                    )
                except Exception as e:
                    logger.warning(
                        "failed_to_fetch_workflow_nodes",
                        workflow_id=workflow["id"],
                        error=str(e),
                    )
                    workflow["nodes"] = []

            workflow["_survey_spec"] = await _fetch_template_survey_spec(
                self.client, "workflow_job_templates", workflow["id"]
            )

            yield workflow

    async def export_parallel(
        self,
        resource_type: str,
        endpoint: str,
        page_size: int = 200,
        max_concurrent_pages: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export workflows with nodes when using parallel page fetches.

        The CLI export path uses ``export_parallel`` for all resource types; without
        this override, workflow nodes are never attached to workflow templates.
        """
        async for workflow in super().export_parallel(
            resource_type=resource_type,
            endpoint=endpoint,
            page_size=page_size,
            max_concurrent_pages=max_concurrent_pages,
            filters=filters,
        ):
            try:
                nodes = await self.client.get_workflow_nodes(workflow["id"])
                nodes = await self._attach_workflow_approval_template_data(nodes)
                workflow["nodes"] = nodes
                logger.debug(
                    "workflow_nodes_fetched",
                    workflow_id=workflow["id"],
                    node_count=len(nodes),
                )
            except Exception as e:
                logger.warning(
                    "failed_to_fetch_workflow_nodes",
                    workflow_id=workflow["id"],
                    error=str(e),
                )
                workflow["nodes"] = []

            workflow["_survey_spec"] = await _fetch_template_survey_spec(
                self.client, "workflow_job_templates", workflow["id"]
            )

            yield workflow


class SystemJobTemplateExporter(ResourceExporter):
    """Exporter for system job template resources.

    System job templates are built-in templates for maintenance tasks
    (cleanup, etc.) that exist in both source and target environments.
    They are exported primarily to map IDs for schedules.
    """

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export system job templates.

        Args:
            filters: Optional query parameters for filtering

        Yields:
            System job template dictionaries
        """
        logger.info("exporting_system_job_templates")
        async for template in self.export_resources(
            resource_type="system_job_templates",
            endpoint="system_job_templates/",
            page_size=self.performance_config.batch_sizes.get("system_job_templates", 50),
            filters=filters,
        ):
            yield template


class RoleDefinitionExporter(ResourceExporter):
    """Exporter for role definition resources (AAP 2.6).

    Role definitions define the available RBAC roles in AAP 2.6.
    They are exported to map source roles to target roles.
    """

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export role definitions.

        Only custom (non-managed) role definitions are exported. Built-in
        managed role definitions (managed=true) are read-only and cannot be
        imported, so they are excluded via the API filter.

        Args:
            filters: Optional query parameters for filtering

        Yields:
            Role definition dictionaries
        """
        logger.info("exporting_role_definitions")
        effective_filters: dict[str, Any] = {"managed": "false"}
        if filters:
            effective_filters.update(filters)
        async for role_def in self.export_resources(
            resource_type="role_definitions",
            endpoint="role_definitions/",
            page_size=self.performance_config.batch_sizes.get("role_definitions", 50),
            filters=effective_filters,
        ):
            yield role_def


class RBACExporter(ResourceExporter):
    """Exporter for RBAC role assignments.

    Reads exported resource files, extracts object_roles from summary_fields,
    queries /roles/{id}/users/ and /roles/{id}/teams/ to build normalized
    assignment records.
    """

    # Resource types that have object_roles in summary_fields
    RBAC_RESOURCE_TYPES = [
        "organizations",
        "teams",
        "projects",
        "inventories",
        "job_templates",
        "workflow_job_templates",
        "credentials",
        "execution_environments",
        "instance_groups",
        "notification_templates",
    ]

    def __init__(
        self,
        client: AAPSourceClient,
        state: MigrationState,
        performance_config: PerformanceConfig,
        export_dir: Path | None = None,
    ):
        """Initialize RBAC exporter.

        Args:
            client: AAP source client instance
            state: Migration state manager
            performance_config: Performance configuration
            export_dir: Directory containing exported resource files
        """
        super().__init__(client, state, performance_config)
        self.export_dir = export_dir or Path("exports")

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export RBAC role assignments by scanning exported resources.

        Reads exported JSON files, extracts object_roles from summary_fields,
        and queries the API for users/teams assigned to each role.

        Args:
            filters: Optional query parameters (unused)

        Yields:
            Normalized assignment records with fields:
            - id: synthetic id
            - resource_type: e.g. "organizations"
            - resource_source_id: source resource ID
            - role_key: e.g. "admin_role"
            - principal_type: "user" or "team"
            - principal_source_id: source user/team ID
            - principal_name: username or team name
        """
        logger.info("exporting_rbac_assignments", export_dir=str(self.export_dir))
        assignment_id = 0

        for resource_type in self.RBAC_RESOURCE_TYPES:
            type_dir = self.export_dir / resource_type
            if not type_dir.exists():
                continue

            for json_file in sorted(type_dir.glob(f"{resource_type}_*.json")):
                try:
                    with open(json_file) as f:
                        resources = json.load(f)
                except Exception as e:
                    logger.warning(
                        "rbac_export_file_error",
                        file=str(json_file),
                        error=str(e),
                    )
                    continue

                for resource in resources:
                    source_id = resource.get("_source_id") or resource.get("id")
                    summary = resource.get("summary_fields", {})
                    object_roles = summary.get("object_roles", {})

                    if not object_roles:
                        continue

                    for role_key, role_info in object_roles.items():
                        role_id = role_info.get("id")
                        if not role_id:
                            continue

                        # Query users for this role
                        for principal_type in ["users", "teams"]:
                            try:
                                page = 1
                                while True:
                                    response = await self.client.get(
                                        f"roles/{role_id}/{principal_type}/",
                                        params={"page": page, "page_size": 200},
                                    )
                                    results = response.get("results", [])

                                    for principal in results:
                                        assignment_id += 1
                                        yield {
                                            "id": assignment_id,
                                            "resource_type": resource_type,
                                            "resource_source_id": source_id,
                                            "role_key": role_key,
                                            "principal_type": principal_type.rstrip("s"),
                                            "principal_source_id": principal.get("id"),
                                            "principal_name": principal.get(
                                                "username", principal.get("name")
                                            ),
                                        }

                                    if not response.get("next"):
                                        break
                                    page += 1

                            except Exception as e:
                                logger.warning(
                                    "rbac_role_query_error",
                                    role_id=role_id,
                                    principal_type=principal_type,
                                    error=str(e),
                                )

        logger.info(
            "rbac_export_completed",
            total_assignments=assignment_id,
        )


class ScheduleExporter(ResourceExporter):
    """Exporter for schedule resources.

    Schedules are associated with unified job templates (job templates,
    workflow templates, or inventory sources).
    """

    # System schedules to skip (these reference built-in system jobs)
    # Note: We now support mapping system_job_templates, so we might not need to skip
    # these if we can map them correctly. However, legacy behavior skips them.
    SYSTEM_SCHEDULES = [
        "Cleanup Job Schedule",
        "Cleanup Activity Schedule",
        "Cleanup Expired Sessions",
        "Cleanup Expired OAuth 2 Tokens",
        "Cleanup Orphaned OAuth 2 Tokens",
    ]

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export schedules.

        Schedules use RRULE format for recurrence patterns.
        They reference unified_job_template which can be any schedulable resource.

        Args:
            filters: Optional query parameters for filtering.
                     Can include 'enabled': True to filter enabled schedules only.

        Yields:
            Schedule dictionaries
        """
        # Filter enabled schedules by default
        if filters is None:
            filters = {}

        # Force enabled=true to filter out disabled schedules
        filters["enabled"] = "true"

        logger.info("exporting_schedules", filters=filters)
        async for schedule in self.export_resources(
            resource_type="schedules",
            endpoint="schedules/",
            page_size=self.performance_config.batch_sizes.get("schedules", 200),
            filters=filters,
        ):
            yield schedule

    async def _process_resource(
        self, resource: dict[str, Any], resource_type: str
    ) -> dict[str, Any] | None:
        """Process schedule resource.

        Skips schedules whose unified_job_template is a system_job — these are
        built-in maintenance schedules (cleanup jobs, session expiry, etc.) that
        cannot be meaningfully imported into a target environment.

        Args:
            resource: Raw resource data from API
            resource_type: Type of resource

        Returns:
            Processed resource or None if should be skipped
        """
        summary = resource.get("summary_fields") or {}
        ujt_summary = summary.get("unified_job_template") or {}
        if ujt_summary.get("unified_job_type") == "system_job":
            schedule_name = resource.get("name", f"id={resource.get('id')}")
            logger.debug(
                "skipping_system_job_schedule",
                name=schedule_name,
                ujt_id=ujt_summary.get("id"),
            )
            return None

        return await super()._process_resource(resource, resource_type)


class WorkflowNodeExporter(ResourceExporter):
    """Exporter for workflow node resources.

    Workflow nodes form a directed graph with edges representing
    success/failure/always paths between nodes.
    """

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export workflow nodes.

        Nodes have edge relationships:
        - success_nodes: Nodes to run on success
        - failure_nodes: Nodes to run on failure
        - always_nodes: Nodes to run always

        Args:
            filters: Optional query parameters for filtering

        Yields:
            Workflow node dictionaries
        """
        logger.info("exporting_workflow_nodes")
        async for node in self.export_resources(
            resource_type="workflow_nodes",
            endpoint="workflow_job_template_nodes/",
            page_size=self.performance_config.batch_sizes.get("workflow_nodes", 200),
            filters=filters,
        ):
            yield node


class ExecutionEnvironmentExporter(ResourceExporter):
    """Exporter for execution environment resources.

    Execution Environments are container images that provide the Ansible
    runtime environment in AAP 2.x.
    """

    def __init__(
        self,
        client: AAPSourceClient,
        state: MigrationState,
        performance_config: PerformanceConfig,
        skip_execution_environment_names: list[str] | None = None,
    ):
        super().__init__(client, state, performance_config)
        self._skip_ee_names = normalized_execution_environment_skip_names(
            skip_execution_environment_names
        )

    def _skip_ee(self, data: dict[str, Any]) -> bool:
        if not self._skip_ee_names:
            return False
        name = data.get("name")
        if not name or not isinstance(name, str):
            return False
        return name.strip().casefold() in self._skip_ee_names

    async def _process_resource(
        self, resource: dict[str, Any], resource_type: str
    ) -> dict[str, Any] | None:
        """Skip configured EE names for sequential export, export_parallel, and export_resources."""
        processed = await super()._process_resource(resource, resource_type)
        if processed is None:
            return None
        if resource_type == "execution_environments" and self._skip_ee(processed):
            self.stats["skipped_count"] += 1
            logger.info(
                "execution_environment_skipped_by_config",
                name=processed.get("name"),
                source_id=processed.get("id"),
            )
            return None
        return processed

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export execution environments.

        Args:
            filters: Optional query parameters for filtering

        Yields:
            Execution environment dictionaries
        """
        logger.info("exporting_execution_environments")
        async for ee in self.export_resources(
            resource_type="execution_environments",
            endpoint="execution_environments/",
            page_size=self.performance_config.batch_sizes.get("execution_environments", 50),
            filters=filters,
        ):
            yield ee


class UserExporter(ResourceExporter):
    """Exporter for user resources."""

    async def _process_resource(
        self, resource: dict[str, Any], resource_type: str
    ) -> dict[str, Any] | None:
        """Attach team memberships and direct role grants to each user export row.

        Both are represented via related-endpoint calls, not inline user fields.
        - ``_team_source_ids``: used by import to re-associate users to teams.
        - ``_user_role_grants``: used by post-import pass to apply classic RBAC
          role grants (e.g. Execute on Job Template) via ``POST users/{id}/roles/``.
        """
        from aap_migration.migration.team_role_grants import parse_user_role_from_api

        processed = await super()._process_resource(resource, resource_type)
        if not processed:
            return None

        source_user_id = processed.get("id")
        if not source_user_id:
            return processed

        # Team memberships
        try:
            teams = await self.client.get_paginated(
                f"users/{source_user_id}/teams/",
                page_size=self.performance_config.batch_sizes.get("teams", 200),
            )
            processed["_team_source_ids"] = [
                int(team["id"]) for team in teams if team.get("id") is not None
            ]
        except Exception as e:
            logger.warning(
                "user_team_memberships_fetch_failed",
                source_user_id=source_user_id,
                error=str(e),
            )
            processed["_team_source_ids"] = []

        # Direct role grants on other resources (classic RBAC)
        grants: list[dict[str, str | int]] = []
        try:
            roles = await self.client.get_paginated(
                f"users/{source_user_id}/roles/",
                page_size=self.performance_config.batch_sizes.get("users", 200),
            )
            for role in roles:
                parsed = parse_user_role_from_api(role)
                if parsed:
                    grants.append(parsed)
        except Exception as e:
            logger.warning(
                "user_roles_fetch_failed",
                source_user_id=source_user_id,
                error=str(e),
            )
        processed["_user_role_grants"] = grants

        return processed

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export users.

        Args:
            filters: Optional query parameters for filtering

        Yields:
            User dictionaries
        """
        logger.info("exporting_users")
        async for user in self.export_resources(
            resource_type="users",
            endpoint="users/",
            page_size=self.performance_config.batch_sizes.get("users", 200),
            filters=filters,
        ):
            yield user


class TeamExporter(ResourceExporter):
    """Exporter for team resources."""

    async def _process_resource(
        self, resource: dict[str, Any], resource_type: str
    ) -> dict[str, Any] | None:
        """Attach role grants where this team is the principal (via ``teams/<id>/roles/``).

        These are distinct from membership in the team (``users/<id>/teams/``). They are
        applied on import with ``POST teams/<id>/roles/`` after target resources exist.
        """
        from aap_migration.migration.team_role_grants import parse_team_role_from_api

        processed = await super()._process_resource(resource, resource_type)
        if not processed:
            return None

        team_id = processed.get("id")
        if not team_id:
            return processed

        grants: list[dict[str, str | int]] = []
        try:
            roles = await self.client.get_paginated(
                f"teams/{team_id}/roles/",
                page_size=self.performance_config.batch_sizes.get("teams", 200),
            )
        except Exception as e:
            logger.warning(
                "team_roles_list_fetch_failed",
                team_id=team_id,
                error=str(e),
            )
            roles = []

        for role in roles:
            parsed = parse_team_role_from_api(role, team_source_id=int(team_id))
            if parsed:
                grants.append(parsed)

        processed["_team_role_grants"] = grants
        return processed

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export teams.

        Args:
            filters: Optional query parameters for filtering

        Yields:
            Team dictionaries
        """
        logger.info("exporting_teams")
        async for team in self.export_resources(
            resource_type="teams",
            endpoint="teams/",
            page_size=self.performance_config.batch_sizes.get("teams", 200),
            filters=filters,
        ):
            yield team


class InstanceExporter(ResourceExporter):
    """Exporter for instance (AAP controller node) resources.

    Instances are individual nodes in the AAP deployment topology.
    They must be exported before instance_groups since groups can reference instances.
    """

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export instances.

        Args:
            filters: Optional query parameters for filtering

        Yields:
            Instance dictionaries
        """
        logger.info("exporting_instances")
        async for instance in self.export_resources(
            resource_type="instances",
            endpoint="instances/",
            page_size=self.performance_config.batch_sizes.get("instances", 50),
            filters=filters,
        ):
            yield instance


class InstanceGroupExporter(ResourceExporter):
    """Exporter for instance group resources.

    Instance groups control where automation jobs execute and enable
    load distribution across AAP instances.
    """

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export instance groups.

        Instance groups are referenced by:
        - Projects
        - Inventories
        - Job Templates
        - Execution Environments

        Args:
            filters: Optional query parameters for filtering

        Yields:
            Instance group dictionaries
        """
        logger.info("exporting_instance_groups")
        async for instance_group in self.export_resources(
            resource_type="instance_groups",
            endpoint="instance_groups/",
            page_size=self.performance_config.batch_sizes.get("instance_groups", 50),
            filters=filters,
        ):
            yield instance_group


class NotificationTemplateExporter(ResourceExporter):
    """Exporter for notification template resources.

    Notification templates define how AAP sends notifications about
    job status (email, Slack, webhook, etc.).
    """

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export notification templates.

        Args:
            filters: Optional query parameters for filtering

        Yields:
            Notification template dictionaries
        """
        logger.info("exporting_notification_templates")
        async for notification in self.export_resources(
            resource_type="notification_templates",
            endpoint="notification_templates/",
            page_size=self.performance_config.batch_sizes.get("notification_templates", 100),
            filters=filters,
        ):
            yield notification


class JobsExporter(ResourceExporter):
    """Exporter for job execution records (historical data).

    Jobs are export-only resources containing historical execution data.
    They are NOT imported to target - used for reporting/auditing purposes.
    """

    async def export(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Export job execution records.

        Args:
            filters: Optional query parameters for filtering (e.g., status, date range)

        Yields:
            Job dictionaries with execution details
        """
        logger.info("exporting_jobs")
        async for job in self.export_resources(
            resource_type="jobs",
            endpoint="jobs/",
            page_size=self.performance_config.batch_sizes.get("jobs", 100),
            filters=filters,
        ):
            yield job


# Factory function for creating exporters
def create_exporter(
    resource_type: str,
    client: AAPSourceClient,
    state: MigrationState,
    performance_config: PerformanceConfig,
    skip_execution_environment_names: list[str] | None = None,
) -> ExporterProtocol:
    """Create appropriate exporter for resource type.

    Args:
        resource_type: Type of resource to export
        client: AAP source client instance
        state: Migration state manager
        performance_config: Performance configuration
        skip_execution_environment_names: Optional EE names to skip (export); defaults to no filter

    Returns:
        Exporter instance implementing ExporterProtocol

    Raises:
        ValueError: If resource_type is not supported
    """
    exporters = {
        "labels": LabelExporter,
        "credential_types": CredentialTypeExporter,
        "organizations": OrganizationExporter,
        "inventory": InventoryExporter,
        "inventory_sources": InventorySourceExporter,
        "groups": InventoryGroupExporter,
        "hosts": HostExporter,
        "credentials": CredentialExporter,
        "credential_input_sources": CredentialInputSourceExporter,
        "projects": ProjectExporter,
        "job_templates": JobTemplateExporter,
        "workflow_job_templates": WorkflowExporter,
        "workflow_job_template_nodes": WorkflowNodeExporter,
        "schedules": ScheduleExporter,
        "execution_environments": ExecutionEnvironmentExporter,
        "users": UserExporter,
        "teams": TeamExporter,
        "instances": InstanceExporter,
        "instance_groups": InstanceGroupExporter,
        "notification_templates": NotificationTemplateExporter,
        "system_job_templates": SystemJobTemplateExporter,
        "jobs": JobsExporter,
        "constructed_inventories": InventoryExporter,
        "role_definitions": RoleDefinitionExporter,
        "role_user_assignments": RBACExporter,
        "role_team_assignments": RBACExporter,
    }

    from aap_migration.resources import normalize_resource_type

    canonical_type = normalize_resource_type(resource_type)
    exporter_class = exporters.get(canonical_type)
    if not exporter_class:
        raise NotImplementedError(
            f"No exporter implemented for resource type: {resource_type} (canonical: {canonical_type}). "
            f"Available exporters: {', '.join(sorted(exporters.keys()))}"
        )

    if canonical_type == "execution_environments":
        return ExecutionEnvironmentExporter(
            client,
            state,
            performance_config,
            skip_execution_environment_names=skip_execution_environment_names,
        )

    return exporter_class(client, state, performance_config)
