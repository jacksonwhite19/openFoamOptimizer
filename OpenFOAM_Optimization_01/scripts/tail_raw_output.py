#!/usr/bin/env python3
"""
Tail raw log output from optimizer runs or case directories.

Examples:
  # Follow latest optimizer run logs
  python3 scripts/tail_raw_output.py --latest

  # Follow a specific run
  python3 scripts/tail_raw_output.py --run-id 20260222_171452

  # Follow a case directory (logs only)
  python3 scripts/tail_raw_output.py --path cases/test_runs/alpha_8_parallel_test

  # Follow a single file from the start
  python3 scripts/tail_raw_output.py --path cases/test_runs/alpha_8_parallel_test/log.simpleFoam.auto --from-start
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tail raw optimizer/case logs.")
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="File or directory to tail. If omitted, uses --results-root with --latest/--run-id.",
    )
    parser.add_argument(
        "--results-root",
        type=Path,
        default=Path("results/optimizer_runs"),
        help="Root directory for optimizer runs (default: results/optimizer_runs).",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Run ID under results-root to follow.",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Follow the most recently modified run under results-root.",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=["log.*"],
        help="Glob pattern(s) to include when tailing a directory (default: log.*).",
    )
    parser.add_argument(
        "--from-start",
        action="store_true",
        help="Print existing content from the start before following.",
    )
    parser.add_argument(
        "--poll-sec",
        type=float,
        default=0.5,
        help="Polling interval in seconds (default: 0.5).",
    )
    parser.add_argument(
        "--show-file",
        action="store_true",
        help="Prefix output with the file path when new files are detected.",
    )
    return parser.parse_args()


def pick_latest_run(root: Path) -> Path | None:
    if not root.exists():
        return None
    runs = [p for p in root.iterdir() if p.is_dir()]
    if not runs:
        return None
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0]


def resolve_target(cfg: argparse.Namespace) -> Path | None:
    if cfg.path is not None:
        return cfg.path
    if cfg.run_id:
        return cfg.results_root / cfg.run_id
    if cfg.latest:
        return pick_latest_run(cfg.results_root)
    return cfg.results_root


def iter_files(root: Path, patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        files.extend(root.rglob(pattern))
    files = [p for p in files if p.is_file()]
    files.sort()
    return files


def tail_files(target: Path, patterns: list[str], from_start: bool, poll_sec: float, show_file: bool) -> None:
    positions: dict[Path, int] = {}
    while True:
        if target.is_file():
            files = [target]
        else:
            files = iter_files(target, patterns)

        for path in files:
            if path not in positions:
                try:
                    with path.open("r", errors="ignore") as fh:
                        if from_start:
                            data = fh.read()
                            if data:
                                if show_file and not target.is_file():
                                    print(f"\n==> {path} <==")
                                print(data, end="")
                            positions[path] = fh.tell()
                        else:
                            fh.seek(0, 2)
                            positions[path] = fh.tell()
                except OSError:
                    continue

        for path in list(positions.keys()):
            if not path.exists():
                continue
            try:
                with path.open("r", errors="ignore") as fh:
                    fh.seek(positions[path])
                    data = fh.read()
                    if data:
                        if show_file and not target.is_file():
                            print(f"\n==> {path} <==")
                        print(data, end="")
                    positions[path] = fh.tell()
            except OSError:
                continue

        time.sleep(poll_sec)


def main() -> None:
    cfg = parse_args()
    target = resolve_target(cfg)
    if target is None:
        raise SystemExit("No run directory found under results-root.")
    if not target.exists():
        raise SystemExit(f"Path not found: {target}")

    try:
        tail_files(target, cfg.include, cfg.from_start, cfg.poll_sec, cfg.show_file)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
