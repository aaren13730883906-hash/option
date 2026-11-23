#!/usr/bin/env python3
"""Create a redacted migration inventory for this project.

The command is read-only. It reports Git state, directory sizes, local-only
files, and external absolute-path references without copying data or secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SIZE_TARGETS = [
    ".deps",
    "data",
    "research",
    "scripts",
    "qmt",
    "monitor",
    "docs",
]
EXCLUDED_DIRS = {".git", ".deps", "data", "research", "__pycache__"}
SENSITIVE_NAMES = {
    "qmt_local_config.py",
    "refresh- token.rtf",
    "ifind_refresh_token.txt",
    ".env",
}
ABSOLUTE_PATH_PATTERN = re.compile(r"/Users/[^\"'`\\s)]+")


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def size_and_count(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    total_size = 0
    file_count = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total_size += child.stat().st_size
                file_count += 1
            except OSError:
                continue
    return total_size, file_count


def human_size(value: int) -> str:
    number = float(value)
    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if number < 1024 or unit == "TiB":
            return f"{number:.1f} {unit}"
        number /= 1024
    return f"{value} B"


def local_only_files() -> list[str]:
    result = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.name in SENSITIVE_NAMES or path.name.startswith(".env"):
            result.append(str(path.relative_to(ROOT)))
    return sorted(result)


def external_references() -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".md", ".txt"}:
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(ROOT).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in ABSOLUTE_PATH_PATTERN.findall(text):
            if str(path.relative_to(ROOT)).startswith("scripts/migration_inventory.py"):
                continue
            references.append(
                {
                    "file": str(path.relative_to(ROOT)),
                    "path": match.rstrip(".,"),
                }
            )
    return references


def build_inventory() -> dict[str, Any]:
    directories: dict[str, Any] = {}
    for name in SIZE_TARGETS:
        size, count = size_and_count(ROOT / name)
        directories[name] = {
            "exists": (ROOT / name).exists(),
            "bytes": size,
            "human_size": human_size(size),
            "files": count,
        }

    return {
        "project_root": str(ROOT),
        "git": {
            "branch": run_git("branch", "--show-current"),
            "head": run_git("rev-parse", "HEAD"),
            "remote_origin": run_git("remote", "get-url", "origin"),
            "status_short": run_git("status", "--short", "--branch").splitlines(),
            "tracked_files": len(run_git("ls-files").splitlines()),
            "untracked_files": len(run_git("ls-files", "--others", "--exclude-standard").splitlines()),
        },
        "directories": directories,
        "local_only_files": local_only_files(),
        "external_absolute_path_references": external_references(),
        "environment": {
            "python": os.sys.version.split()[0],
            "platform": os.sys.platform,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON to this path. Defaults to stdout.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.dumps(build_inventory(), ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(payload)


if __name__ == "__main__":
    main()
