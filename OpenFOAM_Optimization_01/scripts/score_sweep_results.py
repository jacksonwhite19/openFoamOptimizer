#!/usr/bin/env python3
"""
Compute deterministic optimizer score from per-alpha run results.

Inputs:
- optimization_problem_definition.json
- cases/test_runs/<case>/results.json for each alpha in sweep

Output:
- evaluation summary JSON (default: results/sweep_score.json)
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScoreConfig:
    problem_file: Path
    cases_root: Path
    case_prefix: str
    case_suffix: str
    output_file: Path


def parse_args() -> ScoreConfig:
    parser = argparse.ArgumentParser(description="Score alpha sweep results for optimizer use.")
    parser.add_argument(
        "--problem-file",
        type=Path,
        default=Path("optimization_problem_definition.json"),
        help="Optimization problem definition JSON.",
    )
    parser.add_argument(
        "--cases-root",
        type=Path,
        default=Path("cases/test_runs"),
        help="Root containing alpha_<deg>_<suffix> case directories.",
    )
    parser.add_argument(
        "--case-prefix",
        type=str,
        default="alpha",
        help="Case name prefix (default: alpha).",
    )
    parser.add_argument(
        "--case-suffix",
        type=str,
        default="sweep",
        help="Case name suffix (default: sweep).",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=Path("results/sweep_score.json"),
        help="Output score JSON path.",
    )
    args = parser.parse_args()

    return ScoreConfig(
        problem_file=args.problem_file,
        cases_root=args.cases_root,
        case_prefix=args.case_prefix,
        case_suffix=args.case_suffix,
        output_file=args.output_file,
    )


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    return json.loads(path.read_text())


def safe_rel_std(std_val: float | None, mean_val: float | None) -> float | None:
    if std_val is None or mean_val is None:
        return None
    if mean_val == 0:
        return float("inf")
    return abs(std_val / mean_val)


def linear_slope(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xx = sum(x * x for x in xs)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    denom = (n * sum_xx) - (sum_x * sum_x)
    if denom == 0:
        return None
    return ((n * sum_xy) - (sum_x * sum_y)) / denom


def weighted_mean(values: list[float], weights: list[float]) -> float:
    if not values:
        return 0.0
    return sum(v * w for v, w in zip(values, weights))


def load_per_alpha_results(cfg: ScoreConfig, problem: dict[str, Any]) -> list[dict[str, Any]]:
    alphas = problem["sweep_definition"]["alphas_deg"]
    rows: list[dict[str, Any]] = []
    for alpha in alphas:
        case_name = f"{cfg.case_prefix}_{alpha}_{cfg.case_suffix}"
        result_path = cfg.cases_root / case_name / "results.json"
        row: dict[str, Any] = {
            "alpha_deg": alpha,
            "case_name": case_name,
            "result_path": str(result_path),
            "exists": result_path.exists(),
        }
        if row["exists"]:
            payload = read_json(result_path)
            fc = payload.get("force_coefficients", {})
            mq = payload.get("mesh_quality", {})
            row.update(
                {
                    "convergence_status": payload.get("convergence_status"),
                    "CL_mean": fc.get("CL_mean"),
                    "CL_std": fc.get("CL_std"),
                    "CD_mean": fc.get("CD_mean"),
                    "CD_std": fc.get("CD_std"),
                    "CM_mean": fc.get("CM_mean"),
                    "CM_std": fc.get("CM_std"),
                    "L_D_mean": fc.get("L_D_mean"),
                    "mesh_warning": mq.get("mesh_warning"),
                    "failed_checks": mq.get("failed_checks", 0),
                }
            )
        rows.append(row)
    return rows


def compute_score(problem: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    sweep = problem["sweep_definition"]
    constraints = problem["constraints"]
    penalties_cfg = problem["penalties"]

    weights = sweep["alpha_weights"]
    accepted_status = set(constraints["accepted_convergence_status"])

    penalty_total = 0.0
    penalty_breakdown: dict[str, float] = {
        "missing_alpha": 0.0,
        "mesh_warnings": 0.0,
        "mesh_failed_checks": 0.0,
        "nonconverged": 0.0,
        "noise": 0.0,
        "static_margin": 0.0,
        "cma": 0.0,
    }

    ld_values: list[float] = []
    cl_values: list[float] = []
    cm_values: list[float] = []
    alpha_values: list[float] = []
    cl_for_sm: list[float] = []
    cm_for_sm: list[float] = []

    per_alpha_out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        alpha = float(row["alpha_deg"])
        weight = float(weights[i])

        if not row["exists"]:
            p = float(penalties_cfg["missing_alpha_case"])
            penalty_total += p
            penalty_breakdown["missing_alpha"] += p
            per_alpha_out.append(
                {
                    "alpha_deg": alpha,
                    "case_name": row["case_name"],
                    "status": "missing",
                    "penalty": p,
                }
            )
            continue

        status = row.get("convergence_status")
        ld = row.get("L_D_mean")
        cl = row.get("CL_mean")
        cm = row.get("CM_mean")
        cd = row.get("CD_mean")
        failed_checks = int(row.get("failed_checks") or 0)
        mesh_warning = bool(row.get("mesh_warning"))

        if ld is not None:
            ld_values.append(float(ld))
        else:
            ld_values.append(0.0)
        if cl is not None:
            cl_values.append(float(cl))
            cl_for_sm.append(float(cl))
        else:
            cl_values.append(0.0)
        if cm is not None:
            cm_values.append(float(cm))
            cm_for_sm.append(float(cm))
        else:
            cm_values.append(0.0)
        alpha_values.append(alpha)

        alpha_penalty = 0.0
        if mesh_warning:
            p = float(penalties_cfg["mesh_warning_per_alpha"])
            alpha_penalty += p
            penalty_total += p
            penalty_breakdown["mesh_warnings"] += p
        if failed_checks > 0:
            p = failed_checks * float(penalties_cfg["mesh_failed_check_per_count"])
            alpha_penalty += p
            penalty_total += p
            penalty_breakdown["mesh_failed_checks"] += p
        if status not in accepted_status:
            p = float(penalties_cfg["nonconverged_per_alpha"])
            alpha_penalty += p
            penalty_total += p
            penalty_breakdown["nonconverged"] += p

        cl_rel = safe_rel_std(row.get("CL_std"), cl)
        cd_rel = safe_rel_std(row.get("CD_std"), cd)
        cm_rel = safe_rel_std(row.get("CM_std"), cm)
        noise_violations = 0
        if cl_rel is not None and cl_rel > float(constraints["noise_thresholds"]["cl_std_rel_max"]):
            noise_violations += 1
        if cd_rel is not None and cd_rel > float(constraints["noise_thresholds"]["cd_std_rel_max"]):
            noise_violations += 1
        if cm_rel is not None and cm_rel > float(constraints["noise_thresholds"]["cm_std_rel_max"]):
            noise_violations += 1
        if noise_violations > 0:
            p = noise_violations * float(penalties_cfg["noise_threshold_violation_per_metric"])
            alpha_penalty += p
            penalty_total += p
            penalty_breakdown["noise"] += p

        per_alpha_out.append(
            {
                "alpha_deg": alpha,
                "case_name": row["case_name"],
                "status": status,
                "weight": weight,
                "CL_mean": cl,
                "CD_mean": cd,
                "CM_mean": cm,
                "L_D_mean": ld,
                "CL_std_rel": cl_rel,
                "CD_std_rel": cd_rel,
                "CM_std_rel": cm_rel,
                "mesh_warning": mesh_warning,
                "failed_checks": failed_checks,
                "penalty": round(alpha_penalty, 6),
            }
        )

    weighted_ld = weighted_mean(ld_values, [float(w) for w in weights])
    weighted_cl = weighted_mean(cl_values, [float(w) for w in weights])

    cma_slope = linear_slope(alpha_values, cm_values)
    sm_slope = linear_slope(cl_for_sm, cm_for_sm)
    static_margin_percent = None if sm_slope is None else (-sm_slope * 100.0)

    if static_margin_percent is not None:
        sm_min = float(constraints["static_margin_percent_min"])
        sm_max = float(constraints["static_margin_percent_max"])
        if static_margin_percent < sm_min:
            p = (sm_min - static_margin_percent) * float(
                penalties_cfg["static_margin_outside_range_per_percent"]
            )
            penalty_total += p
            penalty_breakdown["static_margin"] += p
        elif static_margin_percent > sm_max:
            p = (static_margin_percent - sm_max) * float(
                penalties_cfg["static_margin_outside_range_per_percent"]
            )
            penalty_total += p
            penalty_breakdown["static_margin"] += p

    if bool(constraints["require_negative_cma_slope"]) and cma_slope is not None and cma_slope >= 0:
        p = float(penalties_cfg["positive_cma_slope"])
        penalty_total += p
        penalty_breakdown["cma"] += p

    score_total = weighted_ld - penalty_total

    feasible = (
        all(r["exists"] for r in rows)
        and (cma_slope is None or cma_slope < 0)
        and (
            static_margin_percent is None
            or (
                float(constraints["static_margin_percent_min"])
                <= static_margin_percent
                <= float(constraints["static_margin_percent_max"])
            )
        )
    )

    status = "ok" if feasible else "constraint_violation"

    return {
        "schema_version": problem["evaluation_contract"]["output_schema_version"],
        "status": status,
        "constraints": {
            "feasible": feasible,
            "static_margin_percent": static_margin_percent,
            "cma_slope": cma_slope,
            "static_margin_percent_min": constraints["static_margin_percent_min"],
            "static_margin_percent_max": constraints["static_margin_percent_max"],
            "require_negative_cma_slope": constraints["require_negative_cma_slope"],
        },
        "objective": {
            "score_total": round(score_total, 6),
            "base_weighted_ld_mean": round(weighted_ld, 6),
            "base_weighted_cl_mean": round(weighted_cl, 6),
            "penalty_total": round(penalty_total, 6),
            "penalties": {k: round(v, 6) for k, v in penalty_breakdown.items()},
        },
        "per_alpha": per_alpha_out,
    }


def main() -> None:
    cfg = parse_args()
    problem = read_json(cfg.problem_file)
    rows = load_per_alpha_results(cfg, problem)
    result = compute_score(problem, rows)

    payload = {
        "problem_name": problem["problem_name"],
        "problem_schema_version": problem["schema_version"],
        "sweep_definition": problem["sweep_definition"],
        "inputs": {
            "problem_file": str(cfg.problem_file),
            "cases_root": str(cfg.cases_root),
            "case_prefix": cfg.case_prefix,
            "case_suffix": cfg.case_suffix,
        },
        "evaluation": result,
    }

    cfg.output_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.output_file.write_text(json.dumps(payload, indent=2))
    print(f"Wrote score output: {cfg.output_file}")
    print(f"score_total: {payload['evaluation']['objective']['score_total']}")
    print(f"feasible: {payload['evaluation']['constraints']['feasible']}")


if __name__ == "__main__":
    main()

