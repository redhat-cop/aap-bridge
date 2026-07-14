"""Helpers for migration artifact directories (exports, xformed, etc.)."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import TypeAlias

OnDirectoryError: TypeAlias = Callable[[str, Path, OSError], None]


def directory_has_contents(path: Path) -> bool:
    """Return True if *path* exists, is a directory, and contains any entries."""
    if not path.is_dir():
        return False
    try:
        return any(path.iterdir())
    except OSError:
        return False


def clear_directory_contents(path: Path) -> None:
    """Remove all children of *path*, preserving the directory itself.

    Safe for bind mounts and named volume mount points (unlike ``rmtree`` on *path*).
    """
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def clear_export_transform_directories(
    export_dir: str | Path,
    transform_dir: str | Path,
    *,
    skip: frozenset[str] | None = None,
    on_error: OnDirectoryError | None = None,
) -> list[str]:
    """Clear export and transform directory contents.

    Returns labels (``exports``, ``xformed``) for directories that were cleared.
    """
    skip_labels = skip or frozenset()
    directories = {
        "exports": Path(export_dir),
        "xformed": Path(transform_dir),
    }
    cleared: list[str] = []
    for label, path in directories.items():
        if label in skip_labels:
            continue
        if not path.is_dir():
            continue
        if not directory_has_contents(path):
            continue
        try:
            clear_directory_contents(path)
            cleared.append(label)
        except OSError as exc:
            if on_error is not None:
                on_error(label, path, exc)
    return cleared
