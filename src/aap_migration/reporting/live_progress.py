"""Live progress display using Rich library.

This module provides a clean, professional progress display for migration operations
using the Rich library's Live display feature. Inspired by guidellm's progress system.

Key Design Principles (from guidellm):
    1. Single Live Display: Create Live instance once, never recreate
    2. Update-Only Pattern: NEVER call reset() on tasks, only update()
    3. Single Task Reuse: For sequential phases, reuse one task with completed=0
    4. Status Icons: Custom column for visual status (✓ complete, • pending, spinner running)
    5. Clean Layout: Multi-line metrics, proper spacing, color coding

The critical insight from guidellm: calling reset() on Progress tasks causes rendering
issues and multiple boxes. Instead, update tasks with new values including completed=0
to effectively reset progress while maintaining a single display.
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.text import Text

from .colors import MigrationColors


class StatusIconColumn(ProgressColumn):
    """Custom column that shows status-specific icons.

    Shows checkmark for complete, warning for complete_with_issues,
    spinner for running, bullet for pending.
    """

    def render(self, task):
        """Render the status icon based on task state."""
        status = task.fields.get("status_text", "pending")

        if status == "complete_with_issues":
            return Text("⚠", style=MigrationColors.WARNING)
        elif "complete" in status:
            return Text("✓", style=MigrationColors.COMPLETE)
        elif "running" in status:
            # Return empty - we'll use SpinnerColumn for running tasks
            return Text("")
        else:  # pending
            return Text("•", style=MigrationColors.PENDING)


@dataclass
class PhaseProgressState:
    """State tracking for a single migration phase.

    Tracks progress, calculates rates, and provides formatted metrics
    for display in the live progress UI.

    Attributes:
        phase_name: Name of the migration phase (e.g., "organizations", "inventories")
        resource_type: Type of resource being migrated
        total_items: Total number of items to migrate in this phase
        completed: Number of items completed (includes both success and failure)
        failed: Number of items that failed
        start_time: Timestamp when phase started
        rate_history: Recent processing rates for smoothing
        last_update: Timestamp of last update
    """

    phase_name: str
    resource_type: str
    total_items: int
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    start_time: float = field(default_factory=time.time)
    rate_history: deque = field(default_factory=lambda: deque(maxlen=10))
    last_update: float = field(default_factory=time.time)

    def update(self, completed: int, failed: int = 0, skipped: int = 0):
        """Update progress and calculate processing rate.

        Args:
            completed: New total completed count
            failed: New total failed count
            skipped: New total skipped count (missing dependencies)
        """
        now = time.time()
        time_delta = now - self.last_update

        if time_delta > 0:
            # Calculate items processed since last update (includes skipped and failed)
            items_delta = (
                (completed - self.completed)
                + (skipped - self.skipped)
                + (failed - self.failed)
            )
            rate = items_delta / time_delta
            self.rate_history.append(rate)

        self.completed = completed
        self.failed = failed
        self.skipped = skipped
        self.last_update = now

    @property
    def success_count(self) -> int:
        """Number of successfully migrated items."""
        return self.completed - self.failed

    @property
    def total_processed(self) -> int:
        """Items handled (exported + skipped + failed) for rate and percentage."""
        return self.completed + self.skipped + self.failed

    @property
    def average_rate(self) -> float:
        """Average processing rate (items/second) based on total throughput."""
        elapsed = self.elapsed_time
        if elapsed <= 0:
            return 0.0
        return self.total_processed / elapsed

    @property
    def elapsed_time(self) -> float:
        """Elapsed time in seconds since phase started."""
        return time.time() - self.start_time

    @property
    def progress_percentage(self) -> float:
        """Progress as percentage (0-100)."""
        if self.total_items == 0:
            return 100.0
        return (self.total_processed / self.total_items) * 100

    @property
    def status_text(self) -> str:
        """Status description for display."""
        # Total processed includes completed + skipped + failed
        total_processed = self.completed + self.skipped + self.failed
        if total_processed >= self.total_items:
            if self.failed > 0:
                return "complete_with_issues"
            return "complete"
        elif self.completed == 0 and self.skipped == 0 and self.failed == 0:
            return "pending"
        else:
            return "running"

    @property
    def status_color(self) -> str:
        """Color for status based on current state."""
        # Total processed includes completed + skipped + failed
        total_processed = self.completed + self.skipped + self.failed
        if total_processed >= self.total_items:
            if self.failed > 0:
                return MigrationColors.ERROR
            return MigrationColors.COMPLETE
        elif self.completed == 0 and self.skipped == 0 and self.failed == 0:
            return MigrationColors.PENDING
        elif self.failed > 0:
            return MigrationColors.WARNING
        else:
            return MigrationColors.RUNNING

    @property
    def formatted_metrics(self) -> str:
        """Format metrics for display (rate, success, failed, skipped, time).

        Returns:
            Formatted string with color-coded metrics (compact for single-line display)
            Always includes Err:X and Skip:X for consistent column alignment
        """
        # Always show error and skip counts for consistent column width alignment
        # Format: "XXX.X/s Err:XXX Skip:XXX XXX.Xs" (fixed width)
        return (
            f"[{MigrationColors.RATE}]{self.average_rate:>5.1f}/s[/{MigrationColors.RATE}]"
            f" [{MigrationColors.ERROR}]Err:{self.failed:<3}[/{MigrationColors.ERROR}]"
            f" [{MigrationColors.WARNING}]Skip:{self.skipped:<3}[/{MigrationColors.WARNING}]"
            f" [{MigrationColors.TIME}]{self.elapsed_time:>5.1f}s[/{MigrationColors.TIME}]"
        )


class MigrationProgressDisplay:
    """Live progress display for migration operations.

    Provides a clean, professional console interface showing real-time
    migration progress with metrics. Uses Rich's Live display to prevent
    output interference and flickering.

    Features:
    - Multi-level display: overall migration + individual phases
    - Real-time metrics: processing rate, success/fail counts, timing
    - Output redirection: captures print statements to avoid interference
    - Conditional display: can be disabled for CI/CD environments

    Example:
        >>> with MigrationProgressDisplay() as progress:
        >>>     progress.set_total_phases(8)
        >>>     phase_id = progress.start_phase("organizations", "organizations", 100)
        >>>     for i in range(100):
        >>>         # ... process item ...
        >>>         progress.update_phase(phase_id, i + 1, 0)
        >>>     progress.complete_phase(phase_id)
    """

    def __init__(
        self, enabled: bool = True, show_stats: bool = False, title: str = "AAP Migration Progress"
    ):
        """Initialize progress display.

        Args:
            enabled: Whether to show live progress (set False for CI/CD)
            show_stats: Whether to show detailed statistics
            title: Display title for the progress panel
        """
        self.enabled = enabled
        self.show_stats = show_stats
        self.title = title

        # Initialize state tracking (needed even when disabled for consistent API)
        self.phase_states: dict[str, PhaseProgressState] = {}
        self.phase_tasks: dict[str, TaskID] = {}
        self.overall_task: TaskID | None = None
        self.total_phases: int = 0
        self.phases_list: list[tuple[str, str]] = []
        self._original_log_handlers = []
        self._null_handler: logging.NullHandler | None = None
        self._live_started = False  # Track if live display has started

        if not self.enabled:
            return

        # Create a console that forces terminal mode
        # This ensures Rich uses live updating even if TTY detection is uncertain
        # We'll also use this console for logging to ensure proper coordination
        self.console = Console(
            force_terminal=True,  # Force terminal mode for ANSI escape sequences
            force_interactive=True,  # Enable interactive features
            stderr=True,  # Output to stderr like logging
            width=120,  # Constrain width to 120 characters
        )

        # Temporarily disable console logging during Live display
        # Store original logging state to restore later
        self._original_log_handlers = []

        # Phase-level progress (individual resource types)
        # Using guidellm-inspired column layout with status icons
        # All information on a single line for better readability
        self.phase_progress = Progress(
            TextColumn("[{task.fields[start_time]}]", style="dim"),
            StatusIconColumn(),  # Custom icon: ✓ for complete, • for pending
            SpinnerColumn(style=MigrationColors.SPINNER),  # Spinner for running only
            TaskProgressColumn(style=MigrationColors.PROGRESS),
            TextColumn("{task.description:<22}", style=MigrationColors.PHASE),
            BarColumn(bar_width=10, style=MigrationColors.PROGRESS),
            TextColumn("{task.completed:>4}/{task.total:<4}"),
            TextColumn("{task.fields[metrics]}"),  # Inline metrics
            console=self.console,  # Use custom console
        )

        # Overall migration progress
        self.overall_progress = Progress(
            TextColumn("[bold]Overall Migration", style=MigrationColors.HEADER),
            BarColumn(bar_width=None, style=MigrationColors.PROGRESS),
            TaskProgressColumn(),
            TextColumn("({task.completed}/{task.total} phases)"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self.console,  # Use custom console
        )

        # Create live display
        # Note: We use RichHandler for logging integration instead of redirect_stdout/stderr
        # RichHandler properly coordinates with Live display to prevent output interference
        self.live = Live(
            Group(
                Panel(
                    self.phase_progress,
                    title=self.title,
                    title_align="left",
                    border_style=MigrationColors.BORDER,
                ),
                self.overall_progress,
            ),
            console=self.console,
            refresh_per_second=10,  # Explicit refresh rate
        )

    def start(self):
        """Prepare the progress display.

        Call this before beginning migration operations.
        Temporarily suppresses console logging to prevent interference.

        Note: The live display is NOT started here. It's started in
        initialize_phases() after all phases are added to avoid jitter.
        """
        if self.enabled:
            # Temporarily disable console logging to prevent interference with Live display
            # Store handlers so we can restore them later
            root_logger = logging.getLogger()
            self._original_log_handlers = root_logger.handlers[:]

            # Remove RichHandler (console output) but keep FileHandler (if any)
            for handler in root_logger.handlers[:]:
                if hasattr(handler, "__class__") and "RichHandler" in handler.__class__.__name__:
                    root_logger.removeHandler(handler)

            # Add a NullHandler so the root logger always has at least one handler.
            # Without this, any WARNING+ log that fires while the Live display is active
            # falls through to Python's logging.lastResort, which writes to sys.stderr.
            # sys.stderr is redirected to FileProxy by Live._enable_redirect_io(), so
            # that write flows through process_renderables(), shifting the cursor down
            # by 1 line per log call and leaving orphan top-border lines in the output.
            self._null_handler = logging.NullHandler()
            root_logger.addHandler(self._null_handler)

            # Note: Live display will be started in initialize_phases() or start_phase()
            # This prevents jitter from tasks being added while display is active

    def stop(self):
        """Stop the live display.

        Call this after migration completes or fails.
        Restores console logging.
        """
        if self.enabled:
            # Only stop Live display if it was actually started
            if self._live_started:
                self.live.stop()
                self._live_started = False

            # Remove the NullHandler added in start() before restoring originals
            if self._null_handler is not None:
                root_logger = logging.getLogger()
                if self._null_handler in root_logger.handlers:
                    root_logger.removeHandler(self._null_handler)
                self._null_handler = None

            # Restore original logging handlers
            if self._original_log_handlers:
                root_logger = logging.getLogger()
                for handler in self._original_log_handlers:
                    if handler not in root_logger.handlers:
                        root_logger.addHandler(handler)
                self._original_log_handlers = []

    def set_total_phases(self, total: int):
        """Set total number of migration phases.

        Note: Should be called BEFORE initialize_phases().
        The overall task is created in initialize_phases() to ensure
        all tasks are added before the Live display starts.

        Args:
            total: Total number of phases in the migration
        """
        self.total_phases = total
        # Overall task creation moved to initialize_phases() to avoid jitter

    def initialize_phases(self, phases: list[tuple[str, str, int]]) -> None:
        """Initialize all phase tasks upfront (guidellm pattern).

        Creates a task for each phase and displays them all as "pending".
        As migration progresses, individual phases update to "running" then "complete".

        IMPORTANT: This method starts the live display AFTER all phases are added
        to prevent jitter from tasks being added while the display is active.

        Args:
            phases: List of (phase_name, description, total_items) tuples

        Example:
            progress.initialize_phases([
                ("organizations", "Organizations", 100),
                ("users", "Users and Teams", 300),
                ...
            ])
        """
        if not self.enabled:
            return

        self.phases_list = [(name, desc) for name, desc, _ in phases]

        # Create a task for each phase, all starting as "pending"
        # This happens BEFORE the live display starts to avoid jitter
        for phase_name, description, total_items in phases:
            # Create pending state
            state = PhaseProgressState(
                phase_name=phase_name,
                resource_type=description,
                total_items=total_items,
            )
            self.phase_states[phase_name] = state

            # Add task to progress display (visible from the start)
            task_id = self.phase_progress.add_task(
                description=description,
                total=total_items,
                completed=0,
                start_time="--:--:--",  # No start time yet
                phase_name=phase_name,
                status_text="pending",  # For StatusIconColumn (shows •)
                status="[dim]pending[/dim]",
                metrics="",  # No metrics yet
                visible=True,  # Make all tasks visible from the start
            )
            self.phase_tasks[phase_name] = task_id

        # Create overall progress task BEFORE starting live display
        # This ensures all tasks exist before rendering begins
        if self.total_phases > 0 and self.overall_task is None:
            self.overall_task = self.overall_progress.add_task(
                "overall",
                total=self.total_phases,
            )

        # NOTE: We DO NOT start the live display here anymore.
        # It will be started in start_phase() when the first phase actually begins.
        # This prevents duplicate header rendering artifacts (Option A in SPEC).

    def initialize_and_start_single_phase(
        self, phase_name: str, resource_type: str, total_items: int
    ) -> str:
        """Initialize and start a single phase immediately (Option C in SPEC).

        Designed for standalone single-phase operations (like Phase 2).
        Avoids the initialize(pending) -> start(running) sequence which can
        cause duplicate header artifacts.

        Args:
            phase_name: Name of the phase
            resource_type: Description of the phase
            total_items: Total items to process

        Returns:
            Phase ID (same as phase_name)
        """
        if not self.enabled:
            return phase_name

        self.phases_list = [(phase_name, resource_type)]

        # Create state
        state = PhaseProgressState(
            phase_name=phase_name,
            resource_type=resource_type,
            total_items=total_items,
        )
        self.phase_states[phase_name] = state

        # Add task directly in RUNNING state (skipping pending)
        task_id = self.phase_progress.add_task(
            description=resource_type,
            total=total_items,
            completed=0,
            start_time=datetime.now().strftime("%H:%M:%S"),
            phase_name=phase_name,
            status_text="running",  # For StatusIconColumn
            status=f"[{MigrationColors.RUNNING}]running[/{MigrationColors.RUNNING}]",
            metrics=state.formatted_metrics,
            visible=True,
        )
        self.phase_tasks[phase_name] = task_id

        # Create overall task
        if self.total_phases > 0 and self.overall_task is None:
            self.overall_task = self.overall_progress.add_task(
                "overall",
                total=self.total_phases,
            )

        # Start live display immediately with the running task.
        # refresh=True triggers an immediate render so that _live_render._shape is
        # populated right away. Without it, _shape stays None until the first
        # auto-refresh tick (~100 ms), and any console print in that window calls
        # process_renderables with no cursor movement, leaving an orphan header line.
        if not self._live_started:
            self.live.start(refresh=True)
            self._live_started = True

        return phase_name

    def start_phase(self, phase_name: str, resource_type: str, total_items: int) -> str:
        """Start tracking a new migration phase.

        Updates the specific phase's task to "running" status.
        If phase wasn't initialized, creates it on the fly.

        Args:
            phase_name: Name of the phase (e.g., "organizations")
            resource_type: Resource type being migrated
            total_items: Total items to migrate in this phase

        Returns:
            Phase ID for use in update_phase() and complete_phase()
        """
        if not self.enabled:
            return phase_name

        # Get or create state tracker
        if phase_name in self.phase_states:
            state = self.phase_states[phase_name]
            # Update total if different (in case estimate changed)
            state.total_items = total_items
            state.start_time = time.time()
        else:
            # Phase wasn't initialized - create it now
            state = PhaseProgressState(
                phase_name=phase_name,
                resource_type=resource_type,
                total_items=total_items,
            )
            self.phase_states[phase_name] = state

        # Get the task for this phase (or create if not exists)
        if phase_name in self.phase_tasks:
            task_id = self.phase_tasks[phase_name]
            # Update existing task to "running"
            self.phase_progress.update(
                task_id,
                description=resource_type,
                total=total_items,
                completed=0,
                start_time=datetime.now().strftime("%H:%M:%S"),
                phase_name=phase_name,
                status_text="running",  # For StatusIconColumn (shows spinner)
                status=f"[{MigrationColors.RUNNING}]running[/{MigrationColors.RUNNING}]",
                metrics=state.formatted_metrics,
            )
        else:
            # Create task on-the-fly if not initialized
            task_id = self.phase_progress.add_task(
                description=resource_type,
                total=total_items,
                completed=0,
                start_time=datetime.now().strftime("%H:%M:%S"),
                phase_name=phase_name,
                status_text="running",
                status=f"[{MigrationColors.RUNNING}]running[/{MigrationColors.RUNNING}]",
                metrics=state.formatted_metrics,
            )
            self.phase_tasks[phase_name] = task_id

        # Start live display AFTER the task is in "running" state to avoid a
        # brief "pending" flash. refresh=True renders immediately so _shape is
        # populated before any console prints can fire process_renderables with
        # a None _shape (which would append an orphan header instead of overwriting).
        if not self._live_started:
            self.live.start(refresh=True)
            self._live_started = True

        return phase_name

    def update_phase(self, phase_id: str, completed: int, failed: int = 0, skipped: int = 0):
        """Update phase progress with new counts.

        Args:
            phase_id: Phase ID from start_phase()
            completed: Total number of completed items
            failed: Total number of failed items
            skipped: Total number of skipped items (missing dependencies)
        """
        if not self.enabled or phase_id not in self.phase_states:
            return

        # Get the specific task for this phase
        if phase_id not in self.phase_tasks:
            return

        task_id = self.phase_tasks[phase_id]
        state = self.phase_states[phase_id]
        state.update(completed, failed, skipped)

        # Update the specific phase's task
        # Bar reflects all handled items (success + skipped + failed)
        total_processed = completed + skipped + failed
        self.phase_progress.update(
            task_id,
            completed=total_processed,
            status_text=state.status_text,  # For StatusIconColumn
            status=f"[{state.status_color}]{state.status_text}[/{state.status_color}]",
            metrics=state.formatted_metrics,
        )

    def complete_phase(self, phase_id: str):
        """Mark phase as complete.

        Args:
            phase_id: Phase ID from start_phase()
        """
        if not self.enabled:
            return

        if phase_id in self.phase_states and phase_id in self.phase_tasks:
            state = self.phase_states[phase_id]
            task_id = self.phase_tasks[phase_id]

            # complete_phase is an explicit end-of-phase signal: always force ✓ 100%.
            # We cannot rely on state.status_text here because concurrent callbacks
            # from delete_resources_parallel may have left total_processed < total_items
            # (e.g. the rendering thread captures a mid-progress frame), causing
            # status_text to return "running" and the spinner to persist.
            total_processed = state.completed + state.skipped + state.failed

            # Only warn if truly nothing happened on a non-empty phase
            if total_processed == 0 and state.total_items > 0:
                final_status = "complete_with_issues"
                final_color = MigrationColors.WARNING
            elif state.failed > 0:
                final_status = "complete_with_issues"
                final_color = MigrationColors.WARNING
            else:
                final_status = "complete"
                final_color = MigrationColors.COMPLETE

            # Force completed = total_items so the bar reaches 100% regardless of
            # how many callbacks fired before this call.
            self.phase_progress.update(
                task_id,
                completed=state.total_items,
                total=state.total_items,
                status_text=final_status,
                status=f"[{final_color}]{final_status}[/{final_color}]",
                metrics=state.formatted_metrics,
            )

        # Update overall progress
        if self.overall_task is not None:
            self.overall_progress.advance(self.overall_task)

    def __enter__(self):
        """Context manager entry - starts live display."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - stops live display."""
        self.stop()
        return False  # Don't suppress exceptions
