"""Bulk operations for AAP 2.6.

This module provides high-performance bulk operations for creating
hosts and launching jobs in parallel. These operations are critical
for migrating large numbers of resources efficiently.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from aap_migration.client.aap_target_client import AAPTargetClient
from aap_migration.client.exceptions import BulkOperationError
from aap_migration.utils.logging import get_logger
from aap_migration.utils.retry import retry_api_call

if TYPE_CHECKING:
    from aap_migration.config import PerformanceConfig

logger = get_logger(__name__)

# Default timeout for bulk operations (seconds)
DEFAULT_BULK_TIMEOUT = 300.0


class BulkOperations:
    """Bulk operations handler for AAP 2.6.

    This class provides methods for bulk creating resources,
    particularly hosts, which is essential for performance when
    migrating 80,000+ inventories.
    """

    def __init__(
        self,
        client: AAPTargetClient,
        performance_config: "PerformanceConfig | None" = None,
    ):
        """Initialize bulk operations handler.

        Args:
            client: AAP target client instance
            performance_config: Optional performance config for timeout settings
        """
        self.client = client
        # Use config timeout or default for backwards compatibility
        self.bulk_timeout = (
            performance_config.bulk_operation_timeout
            if performance_config
            else DEFAULT_BULK_TIMEOUT
        )
        logger.info("bulk_operations_initialized", timeout=self.bulk_timeout)

    async def bulk_create_hosts(
        self,
        inventory_id: int,
        hosts: list[dict[str, Any]],
        batch_size: int = 200,
    ) -> dict[str, Any]:
        """Bulk create hosts in an inventory.

        AAP 2.6 allows creating up to 200 hosts per request via the
        bulk API endpoint. This is significantly faster than creating
        hosts one by one.

        Args:
            inventory_id: Target inventory ID
            hosts: List of host data dictionaries
            batch_size: Number of hosts per batch (max 200)

        Returns:
            Response data with created hosts information

        Raises:
            BulkOperationError: If bulk operation fails
        """
        if batch_size > 200:
            logger.warning(
                "batch_size_exceeded_max",
                requested=batch_size,
                max=200,
            )
            batch_size = 200

        # Prepare hosts data
        hosts_to_create = hosts[:batch_size]

        logger.info(
            "bulk_create_hosts_starting",
            inventory_id=inventory_id,
            host_count=len(hosts_to_create),
        )

        try:
            response = await self._request_bulk_create_hosts(inventory_id, hosts_to_create)

            created_count = len(response.get("hosts", []))
            failed = response.get("failed", [])

            logger.info(
                "bulk_create_hosts_completed",
                inventory_id=inventory_id,
                requested=len(hosts_to_create),
                created=created_count,
                failed=len(failed),
            )

            if failed:
                logger.warning(
                    "bulk_create_hosts_partial_failure",
                    failed_count=len(failed),
                    failed_hosts=failed,
                )

            return response

        except Exception as e:
            logger.error(
                "bulk_create_hosts_failed",
                inventory_id=inventory_id,
                host_count=len(hosts_to_create),
                error=str(e),
            )
            raise BulkOperationError(
                message=f"Bulk host creation failed: {str(e)}",
                failed_items=hosts_to_create,
            ) from e

    @retry_api_call
    async def _request_bulk_create_hosts(
        self,
        inventory_id: int,
        hosts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Execute bulk host creation request with retry logic.

        Args:
            inventory_id: Target inventory ID
            hosts: List of host data

        Returns:
            API response
        """
        # Note: AAPTargetClient base_url already includes /api/controller/v2
        endpoint = "bulk/host_create/"
        payload = {
            "inventory": inventory_id,
            "hosts": hosts,
        }
        # Use configured timeout for bulk operations
        return await self.client.post(endpoint, json_data=payload, timeout=self.bulk_timeout)

    async def bulk_create_hosts_batched(
        self,
        inventory_id: int,
        all_hosts: list[dict[str, Any]],
        batch_size: int = 200,
    ) -> list[dict[str, Any]]:
        """Bulk create hosts in batches.

        For large numbers of hosts, this method automatically chunks
        them into batches of the specified size and creates them
        sequentially.

        Args:
            inventory_id: Target inventory ID
            all_hosts: List of all host data dictionaries
            batch_size: Number of hosts per batch (max 200)

        Returns:
            List of all responses from each batch

        Raises:
            BulkOperationError: If any batch fails
        """
        total_hosts = len(all_hosts)
        batch_size = min(batch_size, 200)

        logger.info(
            "bulk_create_hosts_batched_starting",
            inventory_id=inventory_id,
            total_hosts=total_hosts,
            batch_size=batch_size,
            estimated_batches=(total_hosts + batch_size - 1) // batch_size,
        )

        responses = []
        failed_batches = []

        for i in range(0, total_hosts, batch_size):
            batch_num = (i // batch_size) + 1
            batch = all_hosts[i : i + batch_size]

            logger.info(
                "processing_batch",
                batch_num=batch_num,
                batch_size=len(batch),
                progress=f"{i + len(batch)}/{total_hosts}",
            )

            try:
                response = await self.bulk_create_hosts(
                    inventory_id=inventory_id,
                    hosts=batch,
                    batch_size=batch_size,
                )
                responses.append(response)

            except BulkOperationError as e:
                logger.error(
                    "batch_failed",
                    batch_num=batch_num,
                    error=str(e),
                )
                failed_batches.append({"batch_num": batch_num, "hosts": batch, "error": str(e)})
                # Continue with next batch instead of failing completely

        if failed_batches:
            logger.error(
                "bulk_create_hosts_batched_partial_failure",
                total_batches=len(responses) + len(failed_batches),
                successful_batches=len(responses),
                failed_batches=len(failed_batches),
            )
            # Could optionally raise here or return failed batches info

        logger.info(
            "bulk_create_hosts_batched_completed",
            total_hosts=total_hosts,
            successful_responses=len(responses),
            failed_batches=len(failed_batches),
        )

        return responses

    async def bulk_launch_jobs(
        self,
        job_template_ids: list[int],
        extra_vars: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Bulk launch multiple jobs in parallel.

        This is useful for validation testing where you need to launch
        multiple job templates simultaneously.

        Args:
            job_template_ids: List of job template IDs to launch
            extra_vars: Optional extra variables for all jobs

        Returns:
            Response data with job information

        Raises:
            BulkOperationError: If bulk operation fails
        """
        logger.info(
            "bulk_launch_jobs_starting",
            job_count=len(job_template_ids),
        )

        try:
            response = await self._request_bulk_launch_jobs(job_template_ids, extra_vars)

            launched = response.get("jobs", [])
            failed = response.get("failed", [])

            logger.info(
                "bulk_launch_jobs_completed",
                requested=len(job_template_ids),
                launched=len(launched),
                failed=len(failed),
            )

            if failed:
                logger.warning(
                    "bulk_launch_jobs_partial_failure",
                    failed_count=len(failed),
                    failed_templates=failed,
                )

            return response

        except Exception as e:
            logger.error(
                "bulk_launch_jobs_failed",
                job_count=len(job_template_ids),
                error=str(e),
            )
            raise BulkOperationError(
                message=f"Bulk job launch failed: {str(e)}",
                failed_items=job_template_ids,
            ) from e

    @retry_api_call
    async def _request_bulk_launch_jobs(
        self,
        job_template_ids: list[int],
        extra_vars: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Execute bulk job launch request with retry logic.

        Args:
            job_template_ids: List of job template IDs
            extra_vars: Optional extra variables

        Returns:
            API response
        """
        # Note: AAPTargetClient base_url already includes /api/controller/v2
        endpoint = "bulk/job_launch/"
        payload = {
            "templates": job_template_ids,
            "extra_vars": extra_vars or {},
        }
        # Use configured timeout for bulk operations
        return await self.client.post(endpoint, json_data=payload, timeout=self.bulk_timeout)

    @staticmethod
    def chunk_hosts(
        hosts: list[dict[str, Any]],
        chunk_size: int = 200,
    ) -> list[list[dict[str, Any]]]:
        """Split a list of hosts into chunks for batch processing.

        Args:
            hosts: List of host dictionaries
            chunk_size: Size of each chunk (default 200, API max)

        Returns:
            List of host chunks
        """
        chunk_size = min(chunk_size, 200)
        return [hosts[i : i + chunk_size] for i in range(0, len(hosts), chunk_size)]

    async def bulk_delete_hosts(
        self,
        host_ids: list[int],
        batch_size: int = 500,
    ) -> dict[str, Any]:
        """Bulk delete hosts by IDs.

        AAP 2.6 allows deleting up to 100,000 hosts per request via the
        bulk API endpoint. This is significantly faster than deleting
        hosts one by one.

        Args:
            host_ids: List of host IDs to delete
            batch_size: Number of hosts per batch (max 100,000)

        Returns:
            Response data with deletion results

        Raises:
            BulkOperationError: If bulk operation fails
        """
        if batch_size > 100000:
            logger.warning(
                "batch_size_exceeded_max",
                requested=batch_size,
                max=100000,
            )
            batch_size = 100000

        # Prepare host IDs
        ids_to_delete = host_ids[:batch_size]

        logger.info(
            "bulk_delete_hosts_starting",
            host_count=len(ids_to_delete),
        )

        try:
            response = await self._request_bulk_delete_hosts(ids_to_delete)

            deleted_count = len(response.get("hosts", {}))

            logger.info(
                "bulk_delete_hosts_completed",
                requested=len(ids_to_delete),
                deleted=deleted_count,
            )

            return response

        except Exception as e:
            logger.error(
                "bulk_delete_hosts_failed",
                host_count=len(ids_to_delete),
                error=str(e),
            )
            raise BulkOperationError(
                message=f"Bulk host deletion failed: {str(e)}",
                failed_items=ids_to_delete,
            ) from e

    @retry_api_call
    async def _request_bulk_delete_hosts(
        self,
        host_ids: list[int],
    ) -> dict[str, Any]:
        """Execute bulk host deletion request with retry logic.

        Args:
            host_ids: List of host IDs to delete

        Returns:
            API response
        """
        # Note: AAPTargetClient base_url already includes /api/controller/v2
        endpoint = "bulk/host_delete/"
        payload = {
            "hosts": host_ids,
        }
        # Use configured timeout for bulk operations
        return await self.client.post(endpoint, json_data=payload, timeout=self.bulk_timeout)

    async def bulk_delete_hosts_batched(
        self,
        all_host_ids: list[int],
        batch_size: int = 500,
        progress_callback: Callable | None = None,
    ) -> dict[str, Any]:
        """Bulk delete hosts in batches with progress tracking.

        For large numbers of hosts, this method automatically chunks
        them into batches of the specified size and deletes them
        sequentially.

        Args:
            all_host_ids: List of all host IDs to delete
            batch_size: Number of hosts per batch (default 1000)
            progress_callback: Optional callback(deleted, failed) for progress

        Returns:
            Summary dict with total_requested, total_deleted, total_failed
        """
        total_hosts = len(all_host_ids)
        batch_size = min(batch_size, 100000)

        logger.info(
            "bulk_delete_hosts_batched_starting",
            total_hosts=total_hosts,
            batch_size=batch_size,
            estimated_batches=(total_hosts + batch_size - 1) // batch_size,
        )

        total_deleted = 0
        total_failed = 0

        for i in range(0, total_hosts, batch_size):
            batch_num = (i // batch_size) + 1
            batch = all_host_ids[i : i + batch_size]

            logger.info(
                "processing_delete_batch",
                batch_num=batch_num,
                batch_size=len(batch),
                progress=f"{i + len(batch)}/{total_hosts}",
            )

            try:
                response = await self.bulk_delete_hosts(
                    host_ids=batch,
                    batch_size=batch_size,
                )
                deleted = len(response.get("hosts", {}))
                total_deleted += deleted

            except BulkOperationError as e:
                logger.error(
                    "delete_batch_failed",
                    batch_num=batch_num,
                    error=str(e),
                )
                total_failed += len(batch)
                # Continue with next batch instead of failing completely

            # Call progress callback after each batch
            if progress_callback:
                progress_callback(total_deleted, total_failed)

        logger.info(
            "bulk_delete_hosts_batched_completed",
            total_hosts=total_hosts,
            total_deleted=total_deleted,
            total_failed=total_failed,
        )

        return {
            "total_requested": total_hosts,
            "total_deleted": total_deleted,
            "total_failed": total_failed,
        }

    async def validate_bulk_host_creation(
        self,
        inventory_id: int,
        expected_count: int,
    ) -> bool:
        """Validate that the expected number of hosts were created.

        Args:
            inventory_id: Inventory ID
            expected_count: Expected number of hosts

        Returns:
            True if count matches, False otherwise
        """
        try:
            endpoint = f"inventories/{inventory_id}/hosts/"
            response = await self.client.get(endpoint, params={"page_size": 1})
            actual_count = response.get("count", 0)

            matches = actual_count == expected_count

            logger.info(
                "bulk_creation_validation",
                inventory_id=inventory_id,
                expected=expected_count,
                actual=actual_count,
                matches=matches,
            )

            return matches

        except Exception as e:
            logger.error(
                "bulk_creation_validation_failed",
                inventory_id=inventory_id,
                error=str(e),
            )
            return False

    async def get_bulk_operation_status(
        self,
        operation_id: str,
    ) -> dict[str, Any]:
        """Get status of a bulk operation.

        Some bulk operations return an operation ID that can be used
        to check the status asynchronously.

        Args:
            operation_id: Bulk operation ID

        Returns:
            Operation status data
        """
        # Note: AAPTargetClient base_url already includes /api/controller/v2
        endpoint = f"bulk/operations/{operation_id}/"
        return await self.client.get(endpoint)
