"""Progress display that logs TUI-style lines for Web UI job streams."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime

from aap_migration.reporting.live_progress import PhaseProgressState

LogFn = Callable[[str], None]


class LogMigrationProgressDisplay:
    """Drop-in progress display that writes TUI-like lines to a log callback."""

    def __init__(
        self,
        log: LogFn | None = None,
        enabled: bool = True,
        show_stats: bool = False,
        title: str = "AAP Migration Progress",
    ) -> None:
        self.log = log or (lambda _msg: None)
        self.enabled = enabled
        self.title = title
        self.show_stats = show_stats
        self.phase_states: dict[str, PhaseProgressState] = {}
        self.total_phases = 0
        self._completed_phases = 0
        self._started_at = 0.0

    def start(self) -> None:
        if self.enabled:
            self._started_at = time.time()
            self.log(f"╭─ {self.title} ─╮")

    def stop(self) -> None:
        if not self.enabled or self.total_phases <= 0:
            return
        elapsed = time.time() - self._started_at
        mins, secs = divmod(int(elapsed), 60)
        elapsed_text = f"{mins}m{secs}s" if mins else f"0m{secs}s"
        bar = self._bar(self._completed_phases, self.total_phases)
        self.log(
            f"Overall Migration {bar} "
            f"{int(100 * self._completed_phases / self.total_phases)}% "
            f"({self._completed_phases}/{self.total_phases} phases) "
            f"{elapsed_text} 0:00:00"
        )
        self.log("╰" + "─" * (len(self.title) + 4) + "╯")

    def set_total_phases(self, total: int) -> None:
        self.total_phases = total

    def initialize_phases(self, phases: list[tuple[str, str, int]]) -> None:
        if not self.enabled:
            return
        for phase_name, description, total_items in phases:
            self.phase_states[phase_name] = PhaseProgressState(
                phase_name=phase_name,
                resource_type=description,
                total_items=total_items,
            )

    def initialize_and_start_single_phase(
        self, phase_name: str, resource_type: str, total_items: int
    ) -> str:
        self.set_total_phases(1)
        self.initialize_phases([(phase_name, resource_type, total_items)])
        self.start_phase(phase_name, resource_type, total_items)
        return phase_name

    def start_phase(self, phase_name: str, resource_type: str, total_items: int) -> str:
        if not self.enabled:
            return phase_name
        if phase_name in self.phase_states:
            state = self.phase_states[phase_name]
            state.total_items = total_items
            state.start_time = time.time()
        else:
            self.phase_states[phase_name] = PhaseProgressState(
                phase_name=phase_name,
                resource_type=resource_type,
                total_items=total_items,
            )
        return phase_name

    def update_phase(self, phase_id: str, completed: int, failed: int = 0, skipped: int = 0) -> None:
        if not self.enabled or phase_id not in self.phase_states:
            return
        self.phase_states[phase_id].update(completed, failed, skipped)

    def complete_phase(self, phase_id: str) -> None:
        if not self.enabled or phase_id not in self.phase_states:
            return
        state = self.phase_states[phase_id]
        total_processed = state.completed + state.skipped + state.failed
        if state.total_items > 0 and total_processed < state.total_items:
            state.update(state.total_items, state.failed, state.skipped)
        icon = "✓" if state.failed == 0 else "⚠"
        pct = min(100, int(state.progress_percentage))
        bar = self._bar(state.total_items, state.total_items)
        rate = f"{state.average_rate:.1f}/s"
        self.log(
            f"[{datetime.now().strftime('%H:%M:%S')}] {icon}  {pct:>3}% "
            f"{state.resource_type:<26} {bar} "
            f"{state.total_items:>4}/{state.total_items:<4} "
            f"{rate:>6} Err:{state.failed:<3} Skip:{state.skipped:<3} "
            f"{state.elapsed_time:>5.1f}s"
        )
        self._completed_phases += 1

    @staticmethod
    def _bar(done: int, total: int, width: int = 10) -> str:
        if total <= 0:
            return "━" * width
        filled = int(width * min(done, total) / total)
        return "━" * filled + " " * (width - filled)

    def __enter__(self) -> LogMigrationProgressDisplay:
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.stop()
        return False
