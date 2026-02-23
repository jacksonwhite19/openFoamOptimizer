#!/usr/bin/env python3
"""
Generate a compact optimizer report from a run summary and evaluation files.

Outputs a JSON bundle with:
- objective history
- constraint history
- best design variables
- alpha polars for top candidates
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReportConfig:
    summary_json: Path
    top_n: int
    output_file: Path | None


def parse_args() -> ReportConfig:
    parser = argparse.ArgumentParser(description="Generate optimizer run report JSON.")
    parser.add_argument("--summary-json", type=Path, required=True, help="Optimizer summary.json path")
    parser.add_argument("--top-n", type=int, default=5, help="Top N candidates to include")
    parser.add_argument("--output-file", type=Path, default=None, help="Output report JSON path")
    args = parser.parse_args()
    return ReportConfig(summary_json=args.summary_json, top_n=args.top_n, output_file=args.output_file)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    return json.loads(path.read_text())


def select_score(entry: dict[str, Any]) -> float | None:
    score_robust = entry.get("score_robust")
    if score_robust is not None:
        return float(score_robust)
    score_total = entry.get("score_total")
    if score_total is not None:
        return float(score_total)
    return None


def candidate_design_path(run_dir: Path, candidate_id: str) -> Path:
    designs_dir = run_dir / "designs"
    direct = designs_dir / f"{candidate_id}.json"
    if direct.exists():
        return direct
    # Handle repeat IDs like iter_0001_r2
    if "_r" in candidate_id:
        base = candidate_id.split("_r")[0]
        alt = designs_dir / f"{base}.json"
        if alt.exists():
            return alt
    return direct


def main() -> None:
    cfg = parse_args()
    summary = read_json(cfg.summary_json)
    run_id = summary.get("run_id")
    run_dir = Path("results/optimizer_runs") / run_id if run_id else cfg.summary_json.parent

    output_file = cfg.output_file
    if output_file is None:
        output_file = run_dir / "report.json"

    entries = summary.get("summary", [])

    # Build objective history
    objective_history = []
    constraint_history = []
    for entry in entries:
        candidate_id = entry.get("candidate_id")
        evaluation_json = Path(entry.get("evaluation_json", ""))
        evaluation_payload = None
        if evaluation_json.exists():
            evaluation_payload = read_json(evaluation_json)
        evaluation = (evaluation_payload or {}).get("evaluation", {})
        objective = evaluation.get("objective", {})
        constraints = evaluation.get("constraints", {})

        objective_history.append(
            {
                "candidate_id": candidate_id,
                "score_total": entry.get("score_total"),
                "score_mean": entry.get("score_mean"),
                "score_std": entry.get("score_std"),
                "score_robust": entry.get("score_robust"),
                "status": entry.get("status"),
                "evaluation_json": str(evaluation_json) if evaluation_json else None,
                "resumed": entry.get("resumed", False),
                "penalty_total": objective.get("penalty_total"),
            }
        )

        constraint_history.append(
            {
                "candidate_id": candidate_id,
                "feasible": constraints.get("feasible"),
                "static_margin_percent": constraints.get("static_margin_percent"),
                "cma_slope": constraints.get("cma_slope"),
            }
        )

    ranked = [e for e in entries if select_score(e) is not None]
    ranked.sort(key=lambda r: select_score(r), reverse=True)
    top = ranked[: cfg.top_n]

    top_candidates = []
    for entry in top:
        candidate_id = entry["candidate_id"]
        evaluation_json = Path(entry.get("evaluation_json", ""))
        evaluation_payload = read_json(evaluation_json) if evaluation_json.exists() else {}
        evaluation = evaluation_payload.get("evaluation", {})
        per_alpha = evaluation.get("per_alpha", [])
        design_path = candidate_design_path(run_dir, candidate_id)
        design_payload = read_json(design_path) if design_path.exists() else None

        alpha_polars = {
            "alpha_deg": [row.get("alpha_deg") for row in per_alpha],
            "CL_mean": [row.get("CL_mean") for row in per_alpha],
            "CD_mean": [row.get("CD_mean") for row in per_alpha],
            "CM_mean": [row.get("CM_mean") for row in per_alpha],
            "L_D_mean": [row.get("L_D_mean") for row in per_alpha],
        }

        top_candidates.append(
            {
                "candidate_id": candidate_id,
                "score": select_score(entry),
                "score_total": entry.get("score_total"),
                "score_robust": entry.get("score_robust"),
                "status": entry.get("status"),
                "evaluation_json": str(evaluation_json) if evaluation_json else None,
                "design_json": str(design_path) if design_path.exists() else None,
                "design_variables": design_payload,
                "objective": evaluation.get("objective", {}),
                "constraints": evaluation.get("constraints", {}),
                "alpha_polars": alpha_polars,
            }
        )

    best_id = summary.get("best_candidate_id")
    best_design = None
    if best_id:
        best_design_path = candidate_design_path(run_dir, best_id)
        if best_design_path.exists():
            best_design = read_json(best_design_path)

    report = {
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary_json": str(cfg.summary_json),
        "best_candidate_id": best_id,
        "best_design_variables": best_design,
        "objective_history": objective_history,
        "constraint_history": constraint_history,
        "top_candidates": top_candidates,
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(report, indent=2))
    print(f"Wrote optimizer report: {output_file}")


if __name__ == "__main__":
    main()
