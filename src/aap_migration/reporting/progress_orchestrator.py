"""Progress orchestrator for coordinating multi-phase migration operations.

This module provides a high-level API for managing progress displays across
export, import, and full migration workflows. It eliminates code duplication
by centralizing:
- Pre-fetching resource counts
- Progress display lifecycle management
- Phase tracking and metrics collection
- Consistent error handling

The orchestrator uses MigrationProgressDisplay internally, which already handles
logger suppression during Live display rendering.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from aap_migration.reporting.live_progress import MigrationProgressDisplay
from aap_migration.resources import normalize_resource_type

if TYPE_CHECKING:
    from aap_migration.client.base_client import BaseAPIClient

logger = structlog.get_logger(__name__)


@dataclass
class PhaseStats:
    """Statistics for a completed phase."""

    phase_id: str
    description: str
    total: int
    success: int = 0
    failed: int = 0

    @property
    def completed(self) -> int:
        """Total items processed (success + failed)."""
        return self.success + self.failed


@dataclass
class OrchestratorResult:
    """Result of an orchestrated operation."""

    total_resources: int = 0
    phase_stats: dict[str, PhaseStats] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def add_phase_result(
        self,
        phase_id: str,
        description: str,
        total: int,
        success: int,
        failed: int,
    ) -> None:
        """Record results for a completed phase."""
        self.phase_stats[phase_id] = PhaseStats(
            phase_id=phase_id,
            description=description,
            total=total,
            success=success,
            failed=failed,
        )
        self.total_resources += success

    @property
    def total_failed(self) -> int:
        """Total failed items across all phases."""
        return sum(stats.failed for stats in self.phase_stats.values())


class ProgressOrchestrator:
    """Orchestrates progress display for multi-phase migration operations.

    This class provides a high-level API that:
    1. Pre-fetches resource counts for all phases
    2. Creates a single unified progress display
    3. Tracks metrics and statistics
    4. Handles errors consistently

    Example:
        >>> orchestrator = ProgressOrchestrator(
        ...     title="Export Progress",
        ...     enabled=True
        ... )
        >>>
        >>> # Define phases to process
        >>> phase_configs = [
        ...     ("organizations", OrganizationExporter, "organizations/"),
        ...     ("inventory", InventoryExporter, "inventories/"),
        ... ]
        >>>
        >>> async def process():
        ...     # Pre-fetch counts
        ...     phases = await orchestrator.prefetch_counts(
        ...         client=source_client,
        ...         phase_configs=phase_configs,
        ...         exporter_factory=lambda cls: cls(client, state, perf_config)
        ...     )
        ...
        ...     # Process with unified display
        ...     with orchestrator.progress_context(phases) as tracker:
        ...         for phase_id, desc, total in phases:
        ...             tracker.start_phase(phase_id, desc, total)
        ...             # ... process items ...
        ...             tracker.update(phase_id, count, failed)
        ...             tracker.complete_phase(phase_id)
        ...
        ...     return orchestrator.result
    """

    def __init__(
        self,
        title: str = "AAP Migration Progress",
        enabled: bool = True,
        show_stats: bool = False,
    ):
        """Initialize the orchestrator.

        Args:
            title: Title for the progress display panel
            enabled: Whether to show live progress (False for CI/CD)
            show_stats: Whether to show detailed statistics
        """
        self.title = title
        self.enabled = enabled
        self.show_stats = show_stats
        self.result = OrchestratorResult()
        self._progress: MigrationProgressDisplay | None = None

    async def prefetch_counts(
        self,
        client: "BaseAPIClient",
        phase_configs: list[tuple[str, type, str]],
        state: Any,
        performance_config: Any,
    ) -> list[tuple[str, str, int]]:
        """Pre-fetch resource counts for all phases.

        This is called BEFORE creating the progress display so that
        all phases can be initialized upfront with their totals.

        Args:
            client: API client for fetching counts
            phase_configs: List of (resource_type, ExporterClass, endpoint) tuples
            state: Migration state manager
            performance_config: Performance configuration

        Returns:
            List of (phase_id, description, total_count) tuples ready for progress display
        """
        phases = []

        for resource_type, exporter_class, endpoint in phase_configs:
            # Normalize resource type
            resource_type = normalize_resource_type(resource_type)

            try:
                # Create temporary exporter to get count
                temp_exporter = exporter_class(
                    client=client,
                    state=state,
                    performance_config=performance_config,
                )

                count = await temp_exporter.get_count(endpoint)
                description = resource_type.replace("_", " ").title()
                phases.append((resource_type, description, count))

                logger.debug(
                    "prefetch_count_success",
                    resource_type=resource_type,
                    count=count,
                )
            except Exception as e:
                logger.error(
                    "prefetch_count_failed",
                    resource_type=resource_type,
                    error=str(e),
                )
                # Add with zero count - will be handled during processing
                description = resource_type.replace("_", " ").title()
                phases.append((resource_type, description, 0))
                self.result.errors.append(f"Failed to fetch count for {resource_type}: {e}")

        return phases

    @contextmanager
    def progress_context(
        self,
        phases: list[tuple[str, str, int]],
    ) -> Iterator["PhaseTracker"]:
        """Context manager for progress display lifecycle.

        Creates a single MigrationProgressDisplay instance and initializes
        all phases upfront. The progress display handles logger suppression
        internally.

        Args:
            phases: List of (phase_id, description, total_count) tuples

        Yields:
            PhaseTracker instance for managing individual phases
        """
        if not self.enabled:
            yield DisabledPhaseTracker(self.result)
            return

        # Create and configure progress display
        self._progress = MigrationProgressDisplay(
            title=self.title,
            enabled=self.enabled,
            show_stats=self.show_stats,
        )

        try:
            # Use context manager which handles logger suppression
            with self._progress as progress:
                # Initialize all phases upfront (guidellm pattern)
                progress.initialize_phases(phases)
                progress.set_total_phases(len(phases))

                # Create tracker for phase management
                tracker = PhaseTracker(progress, self.result)
                yield tracker
        finally:
            self._progress = None


class PhaseTracker:
    """Tracks individual phases within an orchestrated progress display.

    Provides a simplified API for common phase operations:
    - start_phase: Mark phase as running
    - update: Update progress counts
    - complete_phase: Mark phase as complete
    """

    def __init__(
        self,
        progress: MigrationProgressDisplay,
        result: OrchestratorResult,
    ):
        """Initialize tracker.

        Args:
            progress: The underlying progress display
            result: Result collector for statistics
        """
        self.progress = progress
        self.result = result
        self._current_phase: str | None = None
        self._phase_info: dict[str, tuple[str, int]] = {}  # phase_id -> (description, total)

    def start_phase(
        self,
        phase_id: str,
        description: str,
        total: int,
    ) -> str:
        """Start a new phase.

        Args:
            phase_id: Unique identifier for the phase
            description: Human-readable description
            total: Total items to process

        Returns:
            The phase_id for use in update() and complete_phase()
        """
        self._current_phase = phase_id
        self._phase_info[phase_id] = (description, total)
        self.progress.start_phase(phase_id, description, total)
        return phase_id

    def update(self, phase_id: str, completed: int, failed: int = 0) -> None:
        """Update phase progress.

        Args:
            phase_id: Phase identifier
            completed: Total items processed so far
            failed: Number of failures so far
        """
        self.progress.update_phase(phase_id, completed, failed)

    def complete_phase(self, phase_id: str, success: int | None = None, failed: int = 0) -> None:
        """Complete the phase and record statistics.

        Args:
            phase_id: Phase identifier
            success: Number of successful items (if None, inferred from last update)
            failed: Number of failed items
        """
        self.progress.complete_phase(phase_id)

        # Record statistics
        if phase_id in self._phase_info:
            description, total = self._phase_info[phase_id]
            if success is None:
                # Get from phase state if available
                if (
                    hasattr(self.progress, "phase_states")
                    and phase_id in self.progress.phase_states
                ):
                    state = self.progress.phase_states[phase_id]
                    success = state.success_count
                    failed = state.failed
                else:
                    success = total - failed

            self.result.add_phase_result(
                phase_id=phase_id,
                description=description,
                total=total,
                success=success,
                failed=failed,
            )

        self._current_phase = None


class DisabledPhaseTracker(PhaseTracker):
    """No-op tracker when progress display is disabled.

    Used for CI/CD environments where live display is not wanted.
    Still records statistics but doesn't update any display.
    """

    def __init__(self, result: OrchestratorResult):
        """Initialize disabled tracker.

        Args:
            result: Result collector for statistics
        """
        self.result = result
        self._phase_info: dict[str, tuple[str, int]] = {}

    def start_phase(self, phase_id: str, description: str, total: int) -> str:
        """Record phase info without display."""
        self._phase_info[phase_id] = (description, total)
        return phase_id

    def update(self, phase_id: str, completed: int, failed: int = 0) -> None:
        """No-op update."""
        pass

    def complete_phase(self, phase_id: str, success: int | None = None, failed: int = 0) -> None:
        """Record statistics without display."""
        if phase_id in self._phase_info:
            description, total = self._phase_info[phase_id]
            if success is None:
                success = total - failed

            self.result.add_phase_result(
                phase_id=phase_id,
                description=description,
                total=total,
                success=success,
                failed=failed,
            )
