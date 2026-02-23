#!/usr/bin/env python3
"""
Optimizer dashboard (no external deps).

Dark mode Foundry style dashboard with:
- run KPIs and history
- active candidate pipeline
- latest evaluation and constraints
- per-alpha performance
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local optimizer dashboard server.")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Bind host (default: 0.0.0.0).")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000).")
    parser.add_argument(
        "--results-root",
        type=Path,
        default=Path("results/optimizer_runs"),
        help="Root directory for optimizer results.",
    )
    parser.add_argument(
        "--recent-limit",
        type=int,
        default=12,
        help="Number of recent evaluations to display.",
    )
    parser.add_argument(
        "--active-window-min",
        type=int,
        default=30,
        help="Window (minutes) to consider a candidate active based on log timestamps.",
    )
    parser.add_argument(
        "--refresh-sec",
        type=int,
        default=10,
        help="Auto-refresh interval in seconds.",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "-"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def fmt_num(val: Any, digits: int = 3) -> str:
    if val is None:
        return "-"
    try:
        return f"{float(val):.{digits}f}"
    except (TypeError, ValueError):
        return str(val)


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def tail_lines(path: Path, max_lines: int = 20, max_chars: int = 4000) -> str:
    if not path.exists():
        return ""
    try:
        data = path.read_text(errors="ignore").splitlines()
    except OSError:
        return ""
    lines = data[-max_lines:]
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[-max_chars:]
    return text


def list_run_dirs(results_root: Path) -> list[Path]:
    if not results_root.exists():
        return []
    return sorted([p for p in results_root.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)


def list_candidate_dirs(run_dir: Path) -> list[Path]:
    if not run_dir.exists():
        return []
    candidates = []
    for p in run_dir.iterdir():
        if not p.is_dir():
            continue
        if (p / "evaluation.json").exists() or list(p.glob("log.*")):
            candidates.append(p)
    return candidates


def flatten_dict(prefix: str, payload: dict[str, Any]) -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    for key, value in payload.items():
        label = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            rows.extend(flatten_dict(label, value))
        else:
            rows.append((label, value))
    return rows


def load_problem_summary() -> dict[str, Any]:
    problem_path = Path("optimization_problem_definition.json")
    payload = read_json(problem_path) or {}
    sweep = payload.get("sweep_definition", {})
    constraints = payload.get("constraints", {})
    return {
        "problem_name": payload.get("problem_name"),
        "score_mode": payload.get("score_mode"),
        "sweep": sweep,
        "constraints": constraints,
    }


def parse_evaluation(eval_path: Path) -> dict[str, Any] | None:
    payload = read_json(eval_path)
    if not payload:
        return None
    evaluation = payload.get("evaluation", {})
    objective = evaluation.get("objective", {})
    constraints = evaluation.get("constraints", {})
    metrics = evaluation.get("metrics", {})
    per_alpha = evaluation.get("per_alpha", [])
    inputs = payload.get("inputs", {})
    return {
        "candidate_id": eval_path.parent.name,
        "path": str(eval_path),
        "mtime": eval_path.stat().st_mtime,
        "status": evaluation.get("status"),
        "objective": objective,
        "constraints": constraints,
        "metrics": metrics,
        "per_alpha": per_alpha,
        "inputs": inputs,
        "sweep_definition": payload.get("sweep_definition"),
        "problem_name": payload.get("problem_name"),
    }


def read_design_values(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = read_json(path) or {}
    return payload


def infer_stage(text: str) -> str:
    t = text.lower()
    if "snappyhexmesh" in t:
        return "Meshing"
    if "simplefoam" in t:
        return "Solver"
    if "blockmesh" in t or "surfacefeatures" in t:
        return "Mesh Prep"
    if "running alpha sweep" in t or "alpha" in t:
        return "Sweep"
    if "generate" in t and "des" in t:
        return "DES"
    return "Working"


def find_recent_evals(run_dir: Path, limit: int) -> list[dict[str, Any]]:
    evals = []
    for cand_dir in list_candidate_dirs(run_dir):
        eval_path = cand_dir / "evaluation.json"
        if not eval_path.exists():
            continue
        parsed = parse_evaluation(eval_path)
        if not parsed:
            continue
        obj = parsed.get("objective", {})
        con = parsed.get("constraints", {})
        evals.append(
            {
                "candidate_id": parsed.get("candidate_id"),
                "mtime": parsed.get("mtime"),
                "status": parsed.get("status"),
                "score_total": obj.get("score_total"),
                "band_ld": obj.get("band_ld") or obj.get("base_weighted_ld_mean"),
                "penalty_total": obj.get("penalty_total"),
                "feasible": con.get("feasible"),
                "static_margin": con.get("static_margin_percent"),
                "sm_category": con.get("sm_category"),
                "hard_reject": con.get("hard_reject_reason"),
            }
        )
    evals.sort(key=lambda r: r["mtime"] or 0, reverse=True)
    return evals[:limit]


def find_latest_eval(run_dir: Path) -> dict[str, Any] | None:
    latest = None
    for cand_dir in list_candidate_dirs(run_dir):
        eval_path = cand_dir / "evaluation.json"
        if not eval_path.exists():
            continue
        parsed = parse_evaluation(eval_path)
        if not parsed:
            continue
        if latest is None or (parsed.get("mtime") or 0) > (latest.get("mtime") or 0):
            latest = parsed
    if not latest:
        return None
    design_path = latest.get("inputs", {}).get("design_json")
    if design_path:
        latest["design"] = read_design_values(Path(design_path))
    return latest


def find_active_candidates(run_dir: Path, window_min: int) -> list[dict[str, Any]]:
    active = []
    cutoff = time.time() - (window_min * 60)
    for cand_dir in list_candidate_dirs(run_dir):
        eval_path = cand_dir / "evaluation.json"
        if eval_path.exists():
            continue
        log_candidate = cand_dir / "log.run_candidate.txt"
        log_sweep = cand_dir / "log.run_sweep.txt"
        if not log_candidate.exists() and not log_sweep.exists():
            continue
        mtime = None
        if log_sweep.exists():
            mtime = log_sweep.stat().st_mtime
        elif log_candidate.exists():
            mtime = log_candidate.stat().st_mtime
        if mtime is None or mtime < cutoff:
            continue
        tail_candidate = tail_lines(log_candidate, max_lines=12) if log_candidate.exists() else ""
        tail_sweep = tail_lines(log_sweep, max_lines=12) if log_sweep.exists() else ""
        stage = infer_stage(tail_sweep or tail_candidate)
        active.append(
            {
                "candidate_id": cand_dir.name,
                "log_candidate": str(log_candidate) if log_candidate.exists() else None,
                "log_sweep": str(log_sweep) if log_sweep.exists() else None,
                "log_tail": tail_sweep or tail_candidate,
                "mtime": mtime,
                "stage": stage,
            }
        )
    active.sort(key=lambda r: r["mtime"], reverse=True)
    return active


def summarize_run(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    summary = read_json(summary_path) or {}
    candidates = list_candidate_dirs(run_dir)

    evals = []
    ok = 0
    failed = 0
    best_score = None
    best_id = None
    last_eval_ts = None
    last_eval_id = None

    for cand in candidates:
        eval_path = cand / "evaluation.json"
        if not eval_path.exists():
            continue
        parsed = parse_evaluation(eval_path)
        if not parsed:
            continue
        evals.append(parsed)
        status = parsed.get("status")
        if status == "ok":
            ok += 1
        else:
            failed += 1
        score = parsed.get("objective", {}).get("score_total")
        if score is not None and (best_score is None or score > best_score):
            best_score = score
            best_id = parsed.get("candidate_id")
        mtime = parsed.get("mtime")
        if mtime and (last_eval_ts is None or mtime > last_eval_ts):
            last_eval_ts = mtime
            last_eval_id = parsed.get("candidate_id")

    return {
        "run_id": run_dir.name,
        "summary_path": str(summary_path) if summary_path.exists() else None,
        "evaluated": len(evals),
        "candidates": len(candidates),
        "ok": ok,
        "failed": failed,
        "best_candidate_id": summary.get("best_candidate_id") or best_id,
        "best_score": summary.get("best_score") or best_score,
        "strategy": summary.get("strategy"),
        "mtime": run_dir.stat().st_mtime,
        "last_eval_ts": last_eval_ts,
        "last_eval_id": last_eval_id,
    }


def build_status(cfg: argparse.Namespace) -> dict[str, Any]:
    runs = list_run_dirs(cfg.results_root)
    run_summaries = [summarize_run(r) for r in runs[:5]]
    latest_run = run_summaries[0] if run_summaries else {}
    previous_run = run_summaries[1] if len(run_summaries) > 1 else None

    best_overall = None
    for item in run_summaries:
        score = item.get("best_score")
        if score is None:
            continue
        if best_overall is None or score > best_overall.get("best_score"):
            best_overall = item

    latest_run_dir = runs[0] if runs else None
    active = find_active_candidates(latest_run_dir, cfg.active_window_min) if latest_run_dir else []
    recent = find_recent_evals(latest_run_dir, cfg.recent_limit) if latest_run_dir else []
    latest_eval = find_latest_eval(latest_run_dir) if latest_run_dir else None
    problem = load_problem_summary()

    if active:
        current_work = active[0]
    elif latest_eval:
        current_work = {
            "candidate_id": latest_eval.get("candidate_id"),
            "stage": "Idle",
            "mtime": latest_eval.get("mtime"),
            "log_tail": "Latest evaluation complete.",
        }
    else:
        current_work = None

    return {
        "now": datetime.now().isoformat(timespec="seconds"),
        "results_root": str(cfg.results_root),
        "latest_run": latest_run,
        "previous_run": previous_run,
        "run_history": run_summaries,
        "best_overall": best_overall,
        "active_candidates": active,
        "recent_evaluations": recent,
        "latest_evaluation": latest_eval,
        "problem": problem,
        "current_work": current_work,
    }


def render_html(status: dict[str, Any], refresh_sec: int) -> str:
    latest = status.get("latest_run", {})
    previous = status.get("previous_run") or {}
    run_history = status.get("run_history", [])
    best_overall = status.get("best_overall") or {}
    active = status.get("active_candidates", [])
    recent = status.get("recent_evaluations", [])
    latest_eval = status.get("latest_evaluation") or {}
    current_work = status.get("current_work") or {}
    problem = status.get("problem", {})
    sweep = problem.get("sweep", {})
    constraints = problem.get("constraints", {})

    active_html = ""
    if active:
        blocks = []
        for cand in active:
            tail = escape_html(cand.get("log_tail", ""))
            blocks.append(
                "<div class='panel card'>"
                f"<div class='card-title'>{cand['candidate_id']} <span class='badge stage'>{cand.get('stage')}</span></div>"
                f"<div class='meta'>updated {fmt_ts(cand.get('mtime'))}</div>"
                f"<pre>{tail}</pre>"
                "</div>"
            )
        active_html = "".join(blocks)
    else:
        active_html = "<div class='muted'>No active candidates detected.</div>"

    recent_rows = []
    for r in recent:
        recent_rows.append(
            "<tr>"
            f"<td>{r['candidate_id']}</td>"
            f"<td>{r.get('status')}</td>"
            f"<td>{fmt_num(r.get('score_total'))}</td>"
            f"<td>{fmt_num(r.get('band_ld'))}</td>"
            f"<td>{fmt_num(r.get('penalty_total'))}</td>"
            f"<td>{r.get('feasible')}</td>"
            f"<td>{fmt_num(r.get('static_margin'))}</td>"
            f"<td>{r.get('sm_category') or '-'}" 
            "</td>"
            f"<td>{r.get('hard_reject') or '-'}" 
            "</td>"
            f"<td>{fmt_ts(r.get('mtime'))}</td>"
            "</tr>"
        )

    recent_table = (
        "<table><thead><tr>"
        "<th>candidate</th><th>status</th><th>score</th><th>band L/D</th>"
        "<th>penalty</th><th>feasible</th><th>SM%</th><th>SM cat</th><th>reject</th><th>updated</th>"
        "</tr></thead><tbody>"
        + "".join(recent_rows)
        + "</tbody></table>"
    )

    design = latest_eval.get("design", {})
    constraints_eval = latest_eval.get("constraints", {})
    objective = latest_eval.get("objective", {})
    metrics = latest_eval.get("metrics", {})
    per_alpha = latest_eval.get("per_alpha", [])

    per_alpha_rows = []
    for row in per_alpha:
        per_alpha_rows.append(
            "<tr>"
            f"<td>{row.get('alpha_deg')}</td>"
            f"<td>{row.get('status')}</td>"
            f"<td>{fmt_num(row.get('CL_mean'))}</td>"
            f"<td>{fmt_num(row.get('CD_mean'))}</td>"
            f"<td>{fmt_num(row.get('CM_mean'))}</td>"
            f"<td>{fmt_num(row.get('L_D_mean'))}</td>"
            f"<td>{'yes' if row.get('mesh_warning') else 'no'}</td>"
            f"<td>{row.get('failed_checks')}</td>"
            "</tr>"
        )

    per_alpha_table = (
        "<table><thead><tr>"
        "<th>alpha</th><th>status</th><th>CL</th><th>CD</th><th>CM</th><th>L/D</th><th>mesh warn</th><th>checks</th>"
        "</tr></thead><tbody>"
        + "".join(per_alpha_rows)
        + "</tbody></table>"
    )

    design_rows = "".join(
        f"<div class='kv'><span>{escape_html(str(k))}</span><strong>{fmt_num(v, 3)}</strong></div>"
        for k, v in design.items()
    )

    penalty_rows = ""
    penalties = objective.get("penalties", {}) if isinstance(objective, dict) else {}
    for k, v in penalties.items():
        penalty_rows += f"<div class='kv'><span>{escape_html(str(k))}</span><strong>{fmt_num(v, 3)}</strong></div>"

    metrics_rows = ""
    for k in [
        "root_mm",
        "aspect_ratio",
        "te_sweep_deg",
        "te_x_mm",
        "cg_x_mm",
        "xnp_mm",
        "mac_mm",
        "dcm_dcl",
    ]:
        if k in metrics:
            metrics_rows += f"<div class='kv'><span>{k}</span><strong>{fmt_num(metrics.get(k), 3)}</strong></div>"

    constraint_rows = ""
    for label, value in flatten_dict("", constraints):
        constraint_rows += f"<div class='kv'><span>{escape_html(label)}</span><strong>{fmt_num(value, 3)}</strong></div>"

    sweep_badge = f"{sweep.get('alphas_deg', [])} / mesh={sweep.get('mesh_cores', '-') }"

    history_rows = ""
    for run in run_history:
        history_rows += (
            "<tr>"
            f"<td>{run.get('run_id')}</td>"
            f"<td>{run.get('evaluated') or 0}/{run.get('candidates') or 0}</td>"
            f"<td>{run.get('ok') or 0}</td>"
            f"<td>{run.get('failed') or 0}</td>"
            f"<td>{fmt_num(run.get('best_score'))}</td>"
            f"<td>{run.get('best_candidate_id') or '-'}" 
            "</td>"
            f"<td>{fmt_ts(run.get('last_eval_ts'))}</td>"
            "</tr>"
        )

    history_table = (
        "<table><thead><tr>"
        "<th>run</th><th>evaluated</th><th>ok</th><th>failed</th><th>best score</th><th>best id</th><th>last eval</th>"
        "</tr></thead><tbody>"
        + history_rows
        + "</tbody></table>"
    )

    current_tail = escape_html(current_work.get("log_tail", ""))

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta http-equiv="refresh" content="{refresh_sec}">
  <title>Optimizer Foundry View</title>
  <style>
    :root {{
      --bg: #0b1220;
      --panel: #111827;
      --ink: #e2e8f0;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --accent-2: #22d3ee;
      --grid: #1f2937;
      --warn: #f59e0b;
      --bad: #ef4444;
      --good: #10b981;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", system-ui, -apple-system, sans-serif;
      color: var(--ink);
      background: radial-gradient(1200px 520px at 80% -20%, rgba(30, 64, 175, 0.35), transparent),
                  radial-gradient(900px 520px at 0% 0%, rgba(15, 118, 110, 0.35), transparent),
                  var(--bg);
    }}
    .shell {{ padding: 24px 28px 36px; max-width: 1500px; margin: 0 auto; }}
    header {{ display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 18px; }}
    .title {{ font-weight: 700; letter-spacing: 0.08em; font-size: 12px; text-transform: uppercase; color: var(--muted); }}
    .headline {{ font-size: 26px; font-weight: 700; margin-top: 4px; }}
    .sub {{ color: var(--muted); font-size: 13px; }}
    .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 18px; }}
    .panel {{ background: var(--panel); border: 1px solid var(--grid); border-radius: 12px; box-shadow: 0 12px 28px rgba(2, 6, 23, 0.55); }}
    .kpi {{ padding: 14px 16px; }}
    .kpi-label {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }}
    .kpi-value {{ font-size: 22px; font-weight: 700; margin-top: 6px; }}
    .kpi-sub {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
    .grid {{ display: grid; grid-template-columns: 1.2fr 1fr; gap: 16px; }}
    .card {{ padding: 14px 16px; margin-bottom: 12px; }}
    .card-title {{ font-weight: 600; margin-bottom: 6px; }}
    .meta {{ font-size: 12px; color: var(--muted); margin-bottom: 8px; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; background: #1e293b; color: #cbd5f5; margin-left: 6px; }}
    .badge.stage {{ background: rgba(56, 189, 248, 0.15); color: #7dd3fc; }}
    .kv-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 18px; }}
    .kv {{ display: flex; justify-content: space-between; font-size: 12px; padding: 4px 0; border-bottom: 1px dashed #1f2937; }}
    .kv span {{ color: var(--muted); }}
    .kv strong {{ font-weight: 600; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    th, td {{ border-bottom: 1px solid var(--grid); padding: 6px 8px; text-align: left; }}
    th {{ color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; font-size: 11px; }}
    pre {{ background: #0f172a; color: #e2e8f0; padding: 10px; border-radius: 8px; font-size: 11px; overflow-x: auto; }}
    .muted {{ color: var(--muted); }}
    .section-title {{ font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin: 6px 0 10px; }}
    .stack {{ display: grid; gap: 10px; }}
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div>
        <div class="title">FOUNDATION / OPTIMIZER OPS</div>
        <div class="headline">Run {latest.get('run_id') or '-'} <span class="badge">{problem.get('problem_name') or 'unknown'}</span></div>
        <div class="sub">Updated {status.get('now')} | Sweep {sweep_badge} | Mode {problem.get('score_mode') or '-'}</div>
      </div>
      <div class="sub">results: {status.get('results_root')}</div>
    </header>

    <div class="kpi-grid">
      <div class="panel kpi">
        <div class="kpi-label">Candidates</div>
        <div class="kpi-value">{latest.get('evaluated') or 0} / {latest.get('candidates') or 0}</div>
        <div class="kpi-sub">ok: {latest.get('ok') or 0} | failed: {latest.get('failed') or 0}</div>
      </div>
      <div class="panel kpi">
        <div class="kpi-label">Best Score (Run)</div>
        <div class="kpi-value">{fmt_num(latest.get('best_score'))}</div>
        <div class="kpi-sub">best: {latest.get('best_candidate_id') or '-'}</div>
      </div>
      <div class="panel kpi">
        <div class="kpi-label">Best Score (All)</div>
        <div class="kpi-value">{fmt_num(best_overall.get('best_score'))}</div>
        <div class="kpi-sub">run: {best_overall.get('run_id') or '-'} | {best_overall.get('best_candidate_id') or '-'}</div>
      </div>
      <div class="panel kpi">
        <div class="kpi-label">Latest Score</div>
        <div class="kpi-value">{fmt_num(objective.get('score_total'))}</div>
        <div class="kpi-sub">status: {latest_eval.get('status') or '-'}</div>
      </div>
      <div class="panel kpi">
        <div class="kpi-label">Current Work</div>
        <div class="kpi-value">{current_work.get('candidate_id') or '-'}</div>
        <div class="kpi-sub">stage: {current_work.get('stage') or '-'}</div>
      </div>
    </div>

    <div class="grid">
      <div>
        <div class="section-title">Active Pipeline</div>
        {active_html}

        <div class="section-title" style="margin-top:18px;">Current Work</div>
        <div class="panel card">
          <div class="card-title">{current_work.get('candidate_id') or 'Idle'}</div>
          <div class="meta">updated {fmt_ts(current_work.get('mtime'))} | stage {current_work.get('stage') or '-'}</div>
          <pre>{current_tail or 'No active logs.'}</pre>
        </div>

        <div class="section-title" style="margin-top:18px;">Run History</div>
        <div class="panel card">
          {history_table}
        </div>
      </div>
      <div class="stack">
        <div class="panel card">
          <div class="card-title">Latest Evaluation</div>
          <div class="meta">candidate {latest_eval.get('candidate_id') or '-'} | updated {fmt_ts(latest_eval.get('mtime'))}</div>
          <div class="kv-grid">
            <div class="kv"><span>score_total</span><strong>{fmt_num(objective.get('score_total'))}</strong></div>
            <div class="kv"><span>band_ld</span><strong>{fmt_num(objective.get('band_ld'))}</strong></div>
            <div class="kv"><span>penalty_total</span><strong>{fmt_num(objective.get('penalty_total'))}</strong></div>
            <div class="kv"><span>alpha_center</span><strong>{objective.get('alpha_center') or '-'}</strong></div>
          </div>
          <div class="section-title">Penalty Breakdown</div>
          <div class="kv-grid">{penalty_rows or '<div class="muted">No penalty details</div>'}</div>
        </div>

        <div class="panel card">
          <div class="card-title">Design Variables</div>
          <div class="kv-grid">{design_rows or '<div class="muted">No design data</div>'}</div>
        </div>

        <div class="panel card">
          <div class="card-title">Geometry + Stability Metrics</div>
          <div class="kv-grid">{metrics_rows or '<div class="muted">No metrics</div>'}</div>
        </div>

        <div class="panel card">
          <div class="card-title">Constraint Set</div>
          <div class="kv-grid">{constraint_rows or '<div class="muted">No constraints</div>'}</div>
        </div>

        <div class="panel card">
          <div class="card-title">Previous Run</div>
          <div class="kv-grid">
            <div class="kv"><span>run_id</span><strong>{previous.get('run_id') or '-'}</strong></div>
            <div class="kv"><span>evaluated</span><strong>{previous.get('evaluated') or 0}/{previous.get('candidates') or 0}</strong></div>
            <div class="kv"><span>best_score</span><strong>{fmt_num(previous.get('best_score'))}</strong></div>
            <div class="kv"><span>last_eval</span><strong>{fmt_ts(previous.get('last_eval_ts'))}</strong></div>
          </div>
        </div>
      </div>
    </div>

    <div class="section-title" style="margin-top:18px;">Per-Alpha Performance</div>
    <div class="panel card">
      {per_alpha_table}
    </div>

    <div class="section-title" style="margin-top:18px;">Recent Evaluations</div>
    <div class="panel card">
      {recent_table}
    </div>
  </div>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.startswith("/api/status"):
            status = build_status(self.server.cfg)
            payload = json.dumps(status, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        status = build_status(self.server.cfg)
        html = render_html(status, self.server.cfg.refresh_sec).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    cfg = parse_args()
    server = ThreadingHTTPServer((cfg.host, cfg.port), Handler)
    server.cfg = cfg
    print(f"Dashboard listening on http://{cfg.host}:{cfg.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()