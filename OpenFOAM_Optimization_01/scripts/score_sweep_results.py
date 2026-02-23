#!/usr/bin/env python3
"""
Compute deterministic optimizer score from per-alpha run results.

Inputs:
- optimization_problem_definition.json
- cases/test_runs/<case>/results.json for each alpha in sweep
- design JSON and/or DES file for geometry-based constraints

Output:
- evaluation summary JSON (default: results/sweep_score.json)
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
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
    design_json: Path | None
    des_file: Path | None


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
    parser.add_argument(
        "--design-json",
        type=Path,
        default=None,
        help="Design JSON with variable values (preferred).",
    )
    parser.add_argument(
        "--des-file",
        type=Path,
        default=None,
        help="DES file to derive geometry values if design JSON is missing.",
    )
    args = parser.parse_args()

    return ScoreConfig(
        problem_file=args.problem_file,
        cases_root=args.cases_root,
        case_prefix=args.case_prefix,
        case_suffix=args.case_suffix,
        output_file=args.output_file,
        design_json=args.design_json,
        des_file=args.des_file,
    )


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    return json.loads(path.read_text())


def parse_des_values(des_file: Path) -> dict[str, float]:
    if not des_file.exists():
        raise FileNotFoundError(f"Missing DES file: {des_file}")

    param_map = {
        "ZVZTXUKAZWE": "span_mm",
        "QTIUMVPVMNM": "sweep_deg",
        "QDYUWWIMJJA": "taper",
        "IQQQXPRMWKO": "tip_mm",
        "VEBCTUVXEVB": "xloc_mm",
        "EZZPYZAMUNE": "ctrl_frac",
        "OJGNBNXLMTG": "fin_sweep_deg",
    }

    values: dict[str, float] = {}
    for line in des_file.read_text().splitlines()[1:]:
        s = line.strip()
        if not s or ":" not in s:
            continue
        left, right = s.rsplit(":", 1)
        param_id = left.split(":", 1)[0].strip()
        if param_id not in param_map:
            continue
        try:
            values[param_map[param_id]] = float(right.strip())
        except ValueError:
            continue
    return values


def load_design_values(cfg: ScoreConfig) -> dict[str, float]:
    values: dict[str, float] = {}
    if cfg.design_json is not None:
        values.update({k: float(v) for k, v in read_json(cfg.design_json).items()})
    if cfg.des_file is not None:
        des_vals = parse_des_values(cfg.des_file)
        for k, v in des_vals.items():
            values.setdefault(k, v)
    return values


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


def extract_band_ld(ld_values: list[float], alphas: list[float], std_scale: float, window: int) -> tuple[float, float | None, list[float]]:
    ld = [max(0.0, float(v)) for v in ld_values]
    if len(ld) < window:
        return 0.001, None, ld
    if all(v == 0.0 for v in ld):
        return 0.001, None, ld

    ld_median = statistics.median(ld)
    if ld_median > 5.0:
        outlier_threshold = 2.0 * ld_median
        for i in range(len(ld)):
            if ld[i] > outlier_threshold:
                if i == 0:
                    ld[i] = ld[i + 1] if i + 1 < len(ld) else ld_median
                elif i == len(ld) - 1:
                    ld[i] = ld[i - 1]
                else:
                    ld[i] = (ld[i - 1] + ld[i + 1]) / 2.0

    best_score = -math.inf
    best_idx: int | None = None
    for i in range(len(ld) - window + 1):
        band = ld[i : i + window]
        mean_val = sum(band) / len(band)
        variance = sum((v - mean_val) ** 2 for v in band) / len(band)
        std_val = variance ** 0.5
        score = mean_val - std_scale * std_val
        if score > best_score:
            best_score = score
            best_idx = i

    if best_idx is None or not math.isfinite(best_score) or best_score <= 0:
        return 0.001, None, ld

    alpha_center = alphas[best_idx + window // 2]
    return best_score, alpha_center, ld


def compute_geometry_penalty(values: dict[str, float], constraints: dict[str, Any], penalties: dict[str, Any]) -> tuple[float, str | None, dict[str, float], list[str]]:
    span = values["span_mm"]
    sweep = values["sweep_deg"]
    xloc = values["xloc_mm"]
    taper = values["taper"]
    tip = values["tip_mm"]

    issues: list[str] = []
    penalty = 0.0

    root = tip / taper if taper != 0 else 0.0
    aspect_ratio = span**2 / (0.5 * (root + tip) * span) if span > 0 else 0.0

    root_thresh = float(constraints["root_crash_threshold_mm"])
    taper_thresh = float(constraints["taper_crash_threshold"])
    if root > root_thresh and taper > taper_thresh:
        crash_penalty = float(penalties["crash_prone_base"]) + float(penalties["crash_prone_scale"]) * (
            root - root_thresh
        ) ** 2
        penalty += crash_penalty
        issues.append(f"crash_prone(root={root:.1f},taper={taper:.2f})")

    ar_target = float(constraints["aspect_ratio_target"])
    ar_hard = float(constraints["aspect_ratio_hard_min"])
    if aspect_ratio < ar_target:
        if aspect_ratio <= ar_hard:
            return float(penalties["hard_reject"]), f"aspect_ratio_impossible_{aspect_ratio:.2f}", {
                "root_mm": root,
                "aspect_ratio": aspect_ratio,
            }, issues
        ar_penalty = float(penalties["low_ar_scale"]) * (ar_target - aspect_ratio) ** 2
        penalty += ar_penalty
        issues.append(f"low_AR({aspect_ratio:.2f})")

    le_sweep_rad = math.radians(sweep)
    te_sweep_angle = math.degrees(math.atan((span / 2.0) * math.tan(le_sweep_rad) / root)) if root > 0 else 0.0
    te_target = float(constraints["te_sweep_target_deg"])
    te_hard = float(constraints["te_sweep_hard_max_deg"])
    if te_sweep_angle > te_target:
        if te_sweep_angle > te_hard:
            return float(penalties["hard_reject"]), f"te_sweep_impossible_{te_sweep_angle:.1f}deg", {
                "root_mm": root,
                "aspect_ratio": aspect_ratio,
                "te_sweep_deg": te_sweep_angle,
            }, issues
        te_penalty = float(penalties["te_sweep_scale"]) * (te_sweep_angle - te_target) ** 2
        penalty += te_penalty
        issues.append(f"high_TE_sweep({te_sweep_angle:.1f})")

    xloc_min_t = float(constraints["xloc_target_min_mm"])
    xloc_max_t = float(constraints["xloc_target_max_mm"])
    xloc_min_h = float(constraints["xloc_hard_min_mm"])
    xloc_max_h = float(constraints["xloc_hard_max_mm"])
    if xloc < xloc_min_t:
        if xloc < xloc_min_h:
            return float(penalties["hard_reject"]), f"xloc_too_forward_{xloc:.1f}mm", {
                "root_mm": root,
                "aspect_ratio": aspect_ratio,
                "te_sweep_deg": te_sweep_angle,
            }, issues
        xloc_penalty = float(penalties["xloc_scale"]) * (xloc_min_t - xloc) ** 2
        penalty += xloc_penalty
        issues.append(f"forward_xloc({xloc:.1f}mm)")

    if xloc > xloc_max_t:
        if xloc > xloc_max_h:
            return float(penalties["hard_reject"]), f"xloc_too_aft_{xloc:.1f}mm", {
                "root_mm": root,
                "aspect_ratio": aspect_ratio,
                "te_sweep_deg": te_sweep_angle,
            }, issues
        xloc_penalty = float(penalties["xloc_scale"]) * (xloc - xloc_max_t) ** 2
        penalty += xloc_penalty
        issues.append(f"aft_xloc({xloc:.1f}mm)")

    tip_le_xloc = xloc + (span / 2.0) * math.tan(le_sweep_rad)
    tip_te_xloc = tip_le_xloc + tip
    if tip_te_xloc < xloc:
        return float(penalties["hard_reject"]), "reverse_taper_geometry", {
            "root_mm": root,
            "aspect_ratio": aspect_ratio,
            "te_sweep_deg": te_sweep_angle,
        }, issues

    te_x = xloc + math.sin(le_sweep_rad) * span + tip
    te_x_target = float(constraints["te_x_target_mm"])
    te_x_hard = float(constraints["te_x_hard_max_mm"])
    if te_x > te_x_target:
        if te_x > te_x_hard:
            return float(penalties["hard_reject"]), f"wingtip_te_x_too_far_{te_x:.1f}mm", {
                "root_mm": root,
                "aspect_ratio": aspect_ratio,
                "te_sweep_deg": te_sweep_angle,
            }, issues
        te_x_penalty = float(penalties["te_x_scale"]) * (te_x - te_x_target) ** 2
        penalty += te_x_penalty
        issues.append(f"long_TE_x({te_x:.1f}mm)")

    metrics = {
        "root_mm": root,
        "aspect_ratio": aspect_ratio,
        "te_sweep_deg": te_sweep_angle,
        "te_x_mm": te_x,
    }
    return penalty, None, metrics, issues


def compute_static_margin(
    alphas: list[float],
    cm_values: list[float],
    cl_values: list[float],
    mac_mm: float,
    xref_mm: float,
    cg_x_mm: float,
) -> tuple[float | None, float, float, float | None]:
    cm_slope = linear_slope(alphas, cm_values)
    cl_slope = linear_slope(alphas, cl_values)
    if cm_slope is None or cl_slope is None:
        return None, 0.0, 0.0, None

    if abs(cl_slope) < 0.01:
        cl_slope = 0.08 if cl_slope >= 0 else -0.08

    dcm_dcl = cm_slope / cl_slope
    xnp = xref_mm - (dcm_dcl * mac_mm)
    static_margin_pct = ((xnp - cg_x_mm) / mac_mm) * 100.0
    return static_margin_pct, dcm_dcl, xnp, cm_slope


def compute_score(problem: dict[str, Any], rows: list[dict[str, Any]], design: dict[str, float]) -> dict[str, Any]:
    sweep = problem["sweep_definition"]
    constraints = problem["constraints"]
    penalties_cfg = problem["penalties"]

    required = ["span_mm", "sweep_deg", "xloc_mm", "taper", "tip_mm"]
    missing = [k for k in required if k not in design]
    if missing:
        raise ValueError(f"Missing design values: {missing}")

    geometry_penalty, hard_reject, geom_metrics, geom_issues = compute_geometry_penalty(
        design, constraints["geometry"], penalties_cfg["geometry"]
    )

    alphas = [float(a) for a in sweep["alphas_deg"]]
    ld_values: list[float] = []
    cl_values: list[float] = []
    cm_values: list[float] = []

    per_alpha_out: list[dict[str, Any]] = []
    for row in rows:
        alpha = float(row["alpha_deg"])
        status = "missing"
        ld = None
        cl = None
        cd = None
        cm = None
        if row["exists"]:
            status = row.get("convergence_status") or "unknown"
            ld = row.get("L_D_mean")
            cl = row.get("CL_mean")
            cd = row.get("CD_mean")
            cm = row.get("CM_mean")

        ld_values.append(float(ld) if ld is not None else 0.0)
        cl_values.append(float(cl) if cl is not None else 0.0)
        cm_values.append(float(cm) if cm is not None else 0.0)

        per_alpha_out.append(
            {
                "alpha_deg": alpha,
                "case_name": row["case_name"],
                "status": status,
                "CL_mean": cl,
                "CD_mean": cd,
                "CM_mean": cm,
                "L_D_mean": ld,
                "mesh_warning": bool(row.get("mesh_warning")),
                "failed_checks": int(row.get("failed_checks") or 0),
            }
        )

    band_cfg = penalties_cfg.get("band_ld", {})
    band_window = int(band_cfg.get("window", 3))
    std_scale = float(band_cfg.get("std_penalty_scale", 0.2))
    band_ld, alpha_center, ld_curve = extract_band_ld(ld_values, alphas, std_scale, band_window)

    ld_min = min(ld_curve) if ld_curve else None
    ld_max = max(ld_curve) if ld_curve else None
    ld_range = (ld_max - ld_min) if ld_min is not None and ld_max is not None else None

    ld_sanity = constraints["ld_sanity"]
    ld_pen = penalties_cfg["ld_sanity"]
    ld_sanity_penalty = 0.0
    ld_sanity_reason = None
    if ld_max is not None and ld_max > float(ld_sanity["max_reasonable"]):
        if ld_max > float(ld_sanity["max_absurd"]):
            ld_sanity_penalty = float(ld_pen["absurd_base"]) + float(ld_pen["absurd_scale"]) * (
                ld_max - float(ld_sanity["max_absurd"])
            ) ** 2
            ld_sanity_reason = f"absurd_ld_{ld_max:.1f}"
    if ld_min is not None and ld_min < 0:
        ld_sanity_penalty = float(ld_pen["negative_base"]) + float(ld_pen["negative_scale"]) * (
            abs(ld_min)
        ) ** 2
        ld_sanity_reason = f"negative_ld_{ld_min:.1f}"

    span_pen_cfg = penalties_cfg["span"]
    span = design["span_mm"]
    span_penalty = 0.0
    if span > float(span_pen_cfg["high_threshold"]):
        span_penalty = float(span_pen_cfg["high_scale"]) * (span - float(span_pen_cfg["high_center"])) ** 2
    elif span < float(span_pen_cfg["low_threshold"]):
        span_penalty = float(span_pen_cfg["low_scale"]) * (float(span_pen_cfg["low_center"]) - span) ** 2

    mac_mm = (2.0 / 3.0) * geom_metrics["root_mm"] * (1.0 + design["taper"] + design["taper"] ** 2) / (
        1.0 + design["taper"]
    )
    cg_x_mm = design.get("xloc_mm", 0.0) - 10.0
    xref_mm = 314.25

    static_margin_pct, dcm_dcl, xnp_mm, cm_slope = compute_static_margin(
        alphas,
        cm_values,
        cl_values,
        mac_mm,
        xref_mm,
        cg_x_mm,
    )

    stability_pen = penalties_cfg["stability"]
    sm_cfg = constraints["stability"]
    crash_penalty = 0.0
    slug_penalty = 0.0
    sm_category = "unknown"

    if static_margin_pct is None or not math.isfinite(static_margin_pct):
        crash_penalty = float(stability_pen["missing_penalty"])
    else:
        sweet_low = float(sm_cfg["sweet_spot_min"])
        sweet_high = float(sm_cfg["sweet_spot_max"])
        acc_low = float(sm_cfg["acceptable_min"])
        acc_high = float(sm_cfg["acceptable_max"])

        if static_margin_pct < acc_low:
            crash_penalty = float(stability_pen["below_accept_scale"]) * (acc_low - static_margin_pct) ** 2
            sm_category = "unstable"
        elif static_margin_pct < sweet_low:
            crash_penalty = float(stability_pen["below_sweet_scale"]) * (sweet_low - static_margin_pct)
            sm_category = "acceptable"
        elif static_margin_pct <= sweet_high:
            sm_category = "sweet_spot"
        elif static_margin_pct <= acc_high:
            slug_penalty = float(stability_pen["above_sweet_scale"]) * (static_margin_pct - sweet_high)
            sm_category = "acceptable"
        else:
            slug_penalty = float(stability_pen["above_accept_scale"]) * (static_margin_pct - acc_high) ** 2
            sm_category = "overly_stable"

    if hard_reject is not None:
        penalty_total = geometry_penalty
        score_total = -geometry_penalty
        status = "geometry_reject"
        feasible = False
    elif ld_sanity_penalty > 0.0:
        penalty_total = geometry_penalty + ld_sanity_penalty
        score_total = -(geometry_penalty + ld_sanity_penalty)
        status = "ld_sanity_fail"
        feasible = False
    else:
        penalty_total = (
            geometry_penalty
            + (0.2 * span_penalty)
            + crash_penalty
            + slug_penalty
        )
        score_total = (0.6 * band_ld) - penalty_total
        status = "ok"
        feasible = True

    return {
        "schema_version": problem["evaluation_contract"]["output_schema_version"],
        "status": status,
        "constraints": {
            "feasible": feasible,
            "static_margin_percent": static_margin_pct,
            "sm_category": sm_category,
            "cma_slope": cm_slope,
            "ld_sanity_reason": ld_sanity_reason,
            "hard_reject_reason": hard_reject,
        },
        "objective": {
            "score_total": round(score_total, 6),
            "band_ld": round(band_ld, 6),
            "alpha_center": alpha_center,
            "base_weighted_ld_mean": round(band_ld, 6),
            "base_weighted_cl_mean": None,
            "penalty_total": round(penalty_total, 6),
            "penalties": {
                "geometry": round(geometry_penalty, 6),
                "span": round(0.2 * span_penalty, 6),
                "stability_crash": round(crash_penalty, 6),
                "stability_slug": round(slug_penalty, 6),
                "ld_sanity": round(ld_sanity_penalty, 6),
            },
        },
        "metrics": {
            "band_ld": band_ld,
            "alpha_center": alpha_center,
            "ld_min": ld_min,
            "ld_max": ld_max,
            "ld_range": ld_range,
            "span_penalty_raw": span_penalty,
            "geometry_issues": geom_issues,
            "root_mm": geom_metrics["root_mm"],
            "aspect_ratio": geom_metrics["aspect_ratio"],
            "te_sweep_deg": geom_metrics["te_sweep_deg"],
            "te_x_mm": geom_metrics["te_x_mm"],
            "cg_x_mm": cg_x_mm,
            "xref_mm": xref_mm,
            "mac_mm": mac_mm,
            "xnp_mm": xnp_mm,
            "dcm_dcl": dcm_dcl,
        },
        "per_alpha": per_alpha_out,
    }


def main() -> None:
    cfg = parse_args()
    problem = read_json(cfg.problem_file)
    rows = load_per_alpha_results(cfg, problem)
    design = load_design_values(cfg)
    result = compute_score(problem, rows, design)

    payload = {
        "problem_name": problem["problem_name"],
        "problem_schema_version": problem["schema_version"],
        "sweep_definition": problem["sweep_definition"],
        "inputs": {
            "problem_file": str(cfg.problem_file),
            "cases_root": str(cfg.cases_root),
            "case_prefix": cfg.case_prefix,
            "case_suffix": cfg.case_suffix,
            "design_json": str(cfg.design_json) if cfg.design_json else None,
            "des_file": str(cfg.des_file) if cfg.des_file else None,
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
