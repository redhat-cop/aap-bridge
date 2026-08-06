#!/usr/bin/env python3
"""Enforce Keep a Changelog-style trailing periods on changelog bullets.

Each change bullet's final content line must end with ``.``, matching the
examples in https://keepachangelog.com/en/1.1.0/.

Default paths:
  CHANGELOG.md
  docs/reference/changelog.md

Usage:
  tools/check_changelog_periods.py              # check defaults
  tools/check_changelog_periods.py --fix       # append missing periods
  tools/check_changelog_periods.py PATH [PATH ...]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_PATHS = (
    Path("CHANGELOG.md"),
    Path("docs/reference/changelog.md"),
)


def _bullet_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """Return (start, end) inclusive line indices for each ``- `` bullet."""
    blocks: list[tuple[int, int]] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.startswith("[") and "]:" in line:
            # Footer links: [unreleased]: https://...
            break
        if line.startswith("- "):
            start = i
            i += 1
            while i < n and lines[i].startswith("  ") and lines[i].strip():
                i += 1
            blocks.append((start, i - 1))
            continue
        i += 1
    return blocks


def _ends_with_period(line: str) -> bool:
    return line.rstrip().endswith(".")


def check(path: Path, *, fix: bool) -> int:
    text = path.read_text(encoding="utf-8")
    if "\r\n" in text:
        raw_lines = text.splitlines()
        newline = "\r\n"
    else:
        raw_lines = text.splitlines()
        newline = "\n"

    blocks = _bullet_blocks(raw_lines)
    violations: list[tuple[int, str]] = []
    for _start, end in blocks:
        last = raw_lines[end]
        if not _ends_with_period(last):
            violations.append((end + 1, last.rstrip()))

    if not violations:
        print(f"{path}: OK ({len(blocks)} change bullets end with '.')")
        return 0

    if not fix:
        print(
            f"{path}: {len(violations)} change bullet(s) missing a trailing period:",
            file=sys.stderr,
        )
        for lineno, content in violations[:30]:
            print(f"  L{lineno}: {content}", file=sys.stderr)
        if len(violations) > 30:
            print(f"  ... and {len(violations) - 30} more", file=sys.stderr)
        return 1

    for _start, end in blocks:
        if not _ends_with_period(raw_lines[end]):
            raw_lines[end] = raw_lines[end].rstrip() + "."

    path.write_text(newline.join(raw_lines) + newline, encoding="utf-8")
    print(f"{path}: fixed {len(violations)} bullet(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Changelog paths (default: CHANGELOG.md and docs/reference/changelog.md)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Append missing trailing periods",
    )
    args = parser.parse_args(argv)
    paths = list(args.paths) if args.paths else list(DEFAULT_PATHS)

    rc = 0
    for path in paths:
        if not path.is_file():
            print(f"error: {path} not found", file=sys.stderr)
            rc = 2
            continue
        result = check(path, fix=args.fix)
        if result != 0 and rc != 2:
            rc = result
    if rc == 1 and not args.fix:
        print(
            "Fix with: python tools/check_changelog_periods.py --fix",
            file=sys.stderr,
        )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
