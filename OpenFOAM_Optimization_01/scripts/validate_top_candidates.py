#!/usr/bin/env python3
"""
High-fidelity validation gate:
- Select top N candidates from a DOE summary.json
- Re-evaluate each with stricter settings (finer alpha sweep, longer endTime)
- Compare low- vs high-fidelity scores
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ValConfig:
    summary_json: Path
    top_n: int
    run_id: str
    problem_file: Path
    alpha_step: int
    end_time: int
    averaging_window: int
    use_cache: bool
    purge_cases: bool
    purge_keep_logs: bool
    dry_run: bool

    @property
    def output_dir(self) -> Path:
        return Path("results/optimizer_runs") / self.run_id / "validation"


def parse_args() -> ValConfig:
    parser = argparse.ArgumentParser(description="Validate top candidates at higher fidelity.")
    parser.add_argument("--summary-json", type=Path, required=True, help="DOE summary.json path")
    parser.add_argument("--top-n", type=int, default=5, help="Number of top candidates to validate")
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Validation run ID (default: <summary_run_id>_val)",
    )
    parser.add_argument(
        "--problem-file",
        type=Path,
        default=Path("optimization_problem_definition.json"),
        help="Optimization problem definition JSON",
    )
    parser.add_argument("--alpha-step", type=int, default=2, help="Validation alpha step (deg)")
    parser.add_argument("--end-time", type=int, default=500, help="Validation solver endTime")
    parser.add_argument("--averaging-window", type=int, default=100, help="Validation averaging window")
    parser.add_argument("--use-cache", action="store_true", help="Reuse cache for validation")
    parser.add_argument("--purge-cases", action="store_true", help="Purge cases after validation")
    parser.add_argument("--purge-keep-logs", action="store_true", help="Keep case logs when purging")
    parser.add_argument("--dry-run", action="store_true", help="Print commands only")
    args = parser.parse_args()

    summary = json.loads(Path(args.summary_json).read_text())
    base_run_id = summary.get("run_id", "run")
    run_id = args.run_id or f"{base_run_id}_val"

    return ValConfig(
        summary_json=args.summary_json,
        top_n=args.top_n,
        run_id=run_id,
        problem_file=args.problem_file,
        alpha_step=args.alpha_step,
        end_time=args.end_time,
        averaging_window=args.averaging_window,
        use_cache=args.use_cache,
        purge_cases=args.purge_cases,
        purge_keep_logs=args.purge_keep_logs,
        dry_run=args.dry_run,
    )


def run_cmd(cmd: list[str], log_path: Path, dry_run: bool) -> None:
    if dry_run:
        print("[dry-run] " + " ".join(cmd))
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log_file:
        proc = subprocess.run(cmd, stdout=log_file, stderr=subprocess.STDOUT, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}. See {log_path}")


def main() -> None:
    cfg = parse_args()
    summary = json.loads(cfg.summary_json.read_text())

    ranked = [s for s in summary.get("summary", []) if s.get("score_total") is not None]
    ranked.sort(key=lambda r: r["score_total"], reverse=True)
    top = ranked[: cfg.top_n]

    output_dir = cfg.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = []

    for entry in top:
        candidate_id = entry["candidate_id"]
        # design JSON is stored under run_id/designs/<candidate>.json
        design_json = Path("results/optimizer_runs") / summary["run_id"] / "designs" / f"{candidate_id}.json"
        log_path = output_dir / f"log.validate_{candidate_id}.txt"

        cmd = [
            "python3",
            "scripts/evaluate_candidate.py",
            "--candidate-id",
            f"{candidate_id}_val",
            "--design-json",
            str(design_json),
            "--run-id",
            cfg.run_id,
            "--problem-file",
            str(cfg.problem_file),
            "--alpha-step",
            str(cfg.alpha_step),
            "--end-time",
            str(cfg.end_time),
            "--averaging-window",
            str(cfg.averaging_window),
        ]
        if cfg.use_cache:
            cmd.append("--use-cache")
        if cfg.purge_cases:
            cmd.append("--purge-cases")
        if cfg.purge_keep_logs:
            cmd.append("--purge-keep-logs")

        run_cmd(cmd, log_path, cfg.dry_run)

        comparison.append(
            {
                "candidate_id": candidate_id,
                "low_fidelity_eval": entry.get("evaluation_json"),
                "high_fidelity_eval": str(
                    Path("results/optimizer_runs") / cfg.run_id / f"{candidate_id}_val" / "evaluation.json"
                ),
            }
        )

    if cfg.dry_run:
        return

    out_path = output_dir / "validation_summary.json"
    out_path.write_text(json.dumps({"validated": comparison}, indent=2))
    print(f"Wrote validation summary: {out_path}")


if __name__ == "__main__":
    main()
