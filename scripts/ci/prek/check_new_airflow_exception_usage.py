#!/usr/bin/env python
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "rich>=13.0.0",
# ]
# ///
"""Check that no new ``raise AirflowException`` usages are introduced.

All *existing* usages are recorded in ``known_airflow_exceptions.txt`` next to
this script (one ``relative/path::stripped_raise_line`` entry per line).  Any
``raise AirflowException`` found in a checked file that is **not** present in
that list is treated as a violation – use a dedicated exception class instead.

Modes
-----
Default (files passed by prek/pre-commit):
    Check only the supplied files; fail on any unlisted usage.

``--all-files``:
    Walk the whole repository and check every ``.py`` file.

``--cleanup``:
    Remove stale entries from the allowlist (entries whose exception no longer
    exists in the corresponding source file). Safe to run at any time; does
    not add new entries.

``--generate``:
    Scan the whole repository and *rebuild* the allowlist from scratch.
    Intended for the initial setup or after a large-scale clean-up sprint.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

console = Console()

REPO_ROOT = Path(__file__).parents[3]

# Match lines that actually raise AirflowException. Comment filtering is done
# in _raise_lines() by skipping lines whose stripped form starts with "#".
_RAISE_RE = re.compile(r"raise\s+AirflowException\b")


class AllowlistManager:
    def __init__(self, allowlist_file: Path) -> None:
        self.allowlist_file = allowlist_file

    def load(self) -> set[str]:
        if not self.allowlist_file.exists():
            return set()
        return {line for line in self.allowlist_file.read_text().splitlines() if line.strip()}

    def save(self, entries: set[str]) -> None:
        self.allowlist_file.write_text("\n".join(sorted(entries)) + "\n")

    def generate(self) -> int:
        console.print(f"Scanning [cyan]{REPO_ROOT}[/cyan] for raise AirflowException …")
        entries: set[str] = set()
        for path in _iter_python_files():
            for line in _raise_lines(path):
                entries.add(_make_entry(path, line))

        self.save(entries)
        console.print(
            f"[green]✓ Generated[/green] [cyan]{self.allowlist_file.relative_to(REPO_ROOT)}[/cyan] "
            f"with [bold]{len(entries)}[/bold] entries."
        )
        return 0

    def cleanup(self) -> int:
        allowlist = self.load()
        if not allowlist:
            console.print("[yellow]Allowlist is empty – nothing to clean up.[/yellow]")
            return 0

        stale: set[str] = set()
        for entry in allowlist:
            rel_str, _, raise_line = entry.partition("::")
            path = REPO_ROOT / rel_str
            if not path.exists() or raise_line not in _raise_lines(path):
                stale.add(entry)

        if stale:
            console.print(
                f"[yellow]Removing {len(stale)} stale entr{'y' if len(stale) == 1 else 'ies'}:[/yellow]"
            )
            for s in sorted(stale):
                console.print(f"  [dim]-[/dim] {s}")
            self.save(allowlist - stale)
            console.print(
                f"\n[green]Updated[/green] [cyan]{self.allowlist_file.relative_to(REPO_ROOT)}[/cyan]"
            )
        else:
            console.print("[green]✓ No stale entries found.[/green]")
        return 0


def _make_entry(path: Path, stripped_line: str) -> str:
    """Generate entry like ``relative/path/to/file.py::raise AirflowException(...)``"""
    return f"{path.relative_to(REPO_ROOT)}::{stripped_line}"


def _raise_lines(path: Path) -> list[str]:
    """Return stripped raise-lines from *path* that match the pattern."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    result = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        # Skip comment lines
        if stripped.startswith("#"):
            continue
        if _RAISE_RE.search(raw_line):
            result.append(stripped)
    return result


def _iter_python_files() -> list[Path]:
    return [
        p.resolve() for p in REPO_ROOT.rglob("*.py") if ".tox" not in p.parts and "__pycache__" not in p.parts
    ]


def _check_airflow_exception_usage(files: list[Path], allowlist: set[str]) -> int:
    # [(file_name, line content), ...]
    violations: list[tuple[Path, str]] = []
    for path in files:
        if not path.exists() or path.suffix != ".py":
            continue
        for line in _raise_lines(path):
            entry = _make_entry(path, line)
            if entry not in allowlist:
                violations.append((path, line))

    if violations:
        console.print(
            Panel.fit(
                "New [bold]raise AirflowException[/bold] usage detected.\n"
                "Define a dedicated exception class or use an existing specific exception.\n"
                "If this usage is intentional and pre-existing, run:\n\n"
                "  [cyan]uv run ./scripts/ci/prek/check_new_airflow_exception_usage.py --generate[/cyan]\n\n"
                "to regenerate the allowlist, then commit the updated\n"
                "[cyan]scripts/ci/prek/known_airflow_exceptions.txt[/cyan].",
                title="[red]❌ Check failed[/red]",
                border_style="red",
            )
        )
        for path, line in violations:
            rel = path.relative_to(REPO_ROOT)
            console.print(f"  [cyan]{rel}[/cyan]  {line}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prevent new `raise AirflowException` usages.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("files", nargs="*", metavar="FILE", help="Files to check (provided by prek)")
    parser.add_argument(
        "--all-files",
        action="store_true",
        help="Check every Python file in the repository",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove stale entries from the allowlist and exit",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Regenerate the allowlist from the current codebase and exit",
    )
    args = parser.parse_args(argv)

    manager = AllowlistManager(Path(__file__).parent / "known_airflow_exceptions.txt")

    if args.generate:
        return manager.generate()

    if args.cleanup:
        return manager.cleanup()

    allowlist = manager.load()

    if args.all_files:
        return _check_airflow_exception_usage(_iter_python_files(), allowlist)

    if not args.files:
        console.print(
            "[yellow]No files provided. Pass filenames or use --all-files to scan the whole repo.[/yellow]"
        )
        return 0

    return _check_airflow_exception_usage([Path(f).resolve() for f in args.files], allowlist)


if __name__ == "__main__":
    raise SystemExit(main())
