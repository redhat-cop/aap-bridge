"""Progress tracking for migration operations.

This module provides real-time progress tracking using tqdm progress bars
and live statistics display during migration.
"""

from types import TracebackType
from typing import Any, Self

from tqdm import tqdm

from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


class ProgressTracker:
    """Tracks and displays migration progress in real-time.

    Uses tqdm to display progress bars for each migration phase and
    resource type, with live statistics updates.
    """

    def __init__(self, total_phases: int = 9, enable: bool = True):
        """Initialize progress tracker.

        Args:
            total_phases: Total number of migration phases
            enable: Whether to enable progress bars (False for CI/automation)
        """
        self.total_phases = total_phases
        self.enable = enable
        self.phase_bar: tqdm | None = None
        self.resource_bar: tqdm | None = None
        self.current_phase = 0

        self.stats: dict[str, Any] = {
            "phases_completed": 0,
            "resources_exported": 0,
            "resources_transformed": 0,
            "resources_imported": 0,
            "resources_failed": 0,
            "resources_skipped": 0,
        }

        if self.enable:
            # Create main phase progress bar
            self.phase_bar = tqdm(
                total=total_phases,
                desc="Migration Progress",
                unit="phase",
                position=0,
                leave=True,
                bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
            )

        logger.info("progress_tracker_initialized", total_phases=total_phases)

    def start_phase(self, phase_name: str, total_resources: int = 0) -> None:
        """Start tracking a new migration phase.

        Args:
            phase_name: Name of the phase being started
            total_resources: Total resources in this phase (0 if unknown)
        """
        self.current_phase += 1

        if self.enable and self.resource_bar:
            self.resource_bar.close()

        if self.enable and total_resources > 0:
            # Create resource progress bar for this phase
            self.resource_bar = tqdm(
                total=total_resources,
                desc=f"  {phase_name}",
                unit="resource",
                position=1,
                leave=False,
                bar_format="  {desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
            )

        logger.info(
            "phase_started",
            phase_name=phase_name,
            phase_number=self.current_phase,
            total_resources=total_resources,
        )

    def complete_phase(self) -> None:
        """Mark current phase as completed."""
        self.stats["phases_completed"] += 1

        if self.enable:
            if self.resource_bar:
                self.resource_bar.close()
                self.resource_bar = None

            if self.phase_bar:
                self.phase_bar.update(1)
                self.phase_bar.set_postfix(
                    exported=self.stats["resources_exported"],
                    imported=self.stats["resources_imported"],
                    failed=self.stats["resources_failed"],
                    skipped=self.stats["resources_skipped"],
                )

        logger.info("phase_completed", phase_number=self.current_phase)

    def update_resource(
        self,
        exported: int = 0,
        transformed: int = 0,
        imported: int = 0,
        failed: int = 0,
        skipped: int = 0,
    ) -> None:
        """Update resource progress and statistics.

        Args:
            exported: Number of resources exported
            transformed: Number of resources transformed
            imported: Number of resources imported
            failed: Number of resources that failed
            skipped: Number of resources skipped
        """
        self.stats["resources_exported"] += exported
        self.stats["resources_transformed"] += transformed
        self.stats["resources_imported"] += imported
        self.stats["resources_failed"] += failed
        self.stats["resources_skipped"] += skipped

        if self.enable and self.resource_bar:
            # Update by total progress (sum of all operations)
            total_update = exported + transformed + imported + failed + skipped
            if total_update > 0:
                self.resource_bar.update(total_update)
                self.resource_bar.set_postfix(
                    imported=self.stats["resources_imported"],
                    failed=self.stats["resources_failed"],
                    skipped=self.stats["resources_skipped"],
                )

    def set_phase_description(self, description: str) -> None:
        """Update phase description.

        Args:
            description: New description for current phase
        """
        if self.enable and self.resource_bar:
            self.resource_bar.set_description(f"  {description}")

    def get_stats(self) -> dict[str, int]:
        """Get current statistics.

        Returns:
            Dictionary with current statistics
        """
        return self.stats.copy()

    def close(self) -> None:
        """Close all progress bars."""
        if self.enable:
            if self.resource_bar:
                self.resource_bar.close()
                self.resource_bar = None

            if self.phase_bar:
                self.phase_bar.close()
                self.phase_bar = None

        logger.info("progress_tracker_closed", final_stats=self.stats)

    def __enter__(self) -> Self:
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit."""
        self.close()


class LiveStats:
    """Displays live statistics during migration.

    Provides a summary view of migration statistics that updates
    in real-time, separate from progress bars.
    """

    def __init__(self, enable: bool = True):
        """Initialize live stats display.

        Args:
            enable: Whether to enable live stats display
        """
        self.enable = enable
        self.stats: dict[str, Any] = {
            "start_time": None,
            "current_phase": "",
            "phases_completed": 0,
            "total_phases": 0,
            "resources_exported": 0,
            "resources_imported": 0,
            "resources_failed": 0,
            "estimated_completion": None,
        }

    def update(self, **kwargs: Any) -> None:
        """Update statistics.

        Args:
            **kwargs: Statistics to update
        """
        self.stats.update(kwargs)

        if self.enable:
            self._display_stats()

    def _display_stats(self) -> None:
        """Display current statistics."""
        # This would use rich or similar for fancy display
        # For now, just log
        logger.info("live_stats", **self.stats)

    def get_summary(self) -> dict[str, Any]:
        """Get statistics summary.

        Returns:
            Dictionary with all statistics
        """
        return self.stats.copy()
