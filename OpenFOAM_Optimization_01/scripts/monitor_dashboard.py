#!/usr/bin/env python3
"""
Simple optimization run dashboard (no external deps).

Serves a live HTML page showing:
- active run and candidate (best-effort heuristics)
- recent evaluations and scores
- constraints and objective summary
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
        default=10,
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


def find_recent_evals(run_dir: Path, limit: int) -> list[dict[str, Any]]:
    evals = []
    for cand_dir in list_candidate_dirs(run_dir):
        eval_path = cand_dir / "evaluation.json"
        if not eval_path.exists():
            continue
        payload = read_json(eval_path) or {}
        evaluation = payload.get("evaluation", {})
        objective = evaluation.get("objective", {})
        constraints = evaluation.get("constraints", {})
        evals.append(
            {
                "candidate_id": cand_dir.name,
                "path": str(eval_path),
                "mtime": eval_path.stat().st_mtime,
                "status": evaluation.get("status"),
                "score_total": objective.get("score_total"),
                "weighted_ld": objective.get("base_weighted_ld_mean"),
                "penalty_total": objective.get("penalty_total"),
                "feasible": constraints.get("feasible"),
                "static_margin": constraints.get("static_margin_percent"),
                "cma_slope": constraints.get("cma_slope"),
            }
        )
    evals.sort(key=lambda r: r["mtime"], reverse=True)
    return evals[:limit]


def find_active_candidates(run_dir: Path, window_min: int) -> list[dict[str, Any]]:
    active = []
    cutoff = time.time() - (window_min * 60)
    for cand_dir in list_candidate_dirs(run_dir):
        eval_path = cand_dir / "evaluation.json"
        if eval_path.exists():
            continue
        log_path = cand_dir / "log.run_candidate.txt"
        if not log_path.exists():
            continue
        mtime = log_path.stat().st_mtime
        if mtime < cutoff:
            continue
        active.append(
            {
                "candidate_id": cand_dir.name,
                "log_path": str(log_path),
                "log_tail": tail_lines(log_path, max_lines=15),
                "mtime": mtime,
            }
        )
    active.sort(key=lambda r: r["mtime"], reverse=True)
    return active


def summarize_run(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    summary = read_json(summary_path) or {}
    best_id = summary.get("best_candidate_id")
    best_score = summary.get("best_score")
    evaluated = summary.get("evaluated")
    return {
        "run_id": run_dir.name,
        "summary_path": str(summary_path) if summary_path.exists() else None,
        "evaluated": evaluated,
        "best_candidate_id": best_id,
        "best_score": best_score,
        "strategy": summary.get("strategy"),
        "mtime": run_dir.stat().st_mtime,
    }


def build_status(cfg: argparse.Namespace) -> dict[str, Any]:
    runs = list_run_dirs(cfg.results_root)
    latest_run = runs[0] if runs else None
    run_info = summarize_run(latest_run) if latest_run else {}
    active = find_active_candidates(latest_run, cfg.active_window_min) if latest_run else []
    recent = find_recent_evals(latest_run, cfg.recent_limit) if latest_run else []
    return {
        "now": datetime.now().isoformat(timespec="seconds"),
        "results_root": str(cfg.results_root),
        "latest_run": run_info,
        "active_candidates": active,
        "recent_evaluations": recent,
    }


def render_html(status: dict[str, Any], refresh_sec: int) -> str:
    latest = status.get("latest_run", {})
    active = status.get("active_candidates", [])
    recent = status.get("recent_evaluations", [])

    def row(text: str) -> str:
        return f"<tr><td>{text}</td></tr>"

    active_html = ""
    if active:
        blocks = []
        for cand in active:
            tail = cand.get("log_tail", "").replace("<", "&lt;").replace(">", "&gt;")
            blocks.append(
                f"<div class='card'><div class='title'>{cand['candidate_id']}</div>"
                f"<div class='meta'>log: {cand['log_path']} (updated {fmt_ts(cand['mtime'])})</div>"
                f"<pre>{tail}</pre></div>"
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
            f"<td>{r.get('score_total')}</td>"
            f"<td>{r.get('weighted_ld')}</td>"
            f"<td>{r.get('penalty_total')}</td>"
            f"<td>{r.get('feasible')}</td>"
            f"<td>{r.get('static_margin')}</td>"
            f"<td>{r.get('cma_slope')}</td>"
            f"<td>{fmt_ts(r.get('mtime'))}</td>"
            "</tr>"
        )

    recent_table = (
        "<table><thead><tr>"
        "<th>candidate</th><th>status</th><th>score</th><th>weighted L/D</th>"
        "<th>penalty</th><th>feasible</th><th>SM%</th><th>Cm-alpha</th><th>updated</th>"
        "</tr></thead><tbody>"
        + "".join(recent_rows)
        + "</tbody></table>"
    )

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta http-equiv="refresh" content="{refresh_sec}">
  <title>Optimizer Monitor</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #111; }}
    h1 {{ margin-bottom: 6px; }}
    .muted {{ color: #666; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .card {{ border: 1px solid #ddd; padding: 12px; border-radius: 6px; margin-bottom: 12px; }}
    .title {{ font-weight: 600; margin-bottom: 6px; }}
    .meta {{ font-size: 12px; color: #666; margin-bottom: 6px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border: 1px solid #ddd; padding: 6px 8px; font-size: 12px; }}
    th {{ background: #f7f7f7; text-align: left; }}
    pre {{ background: #f7f7f7; padding: 8px; overflow-x: auto; }}
  </style>
</head>
<body>
  <h1>Optimizer Monitor</h1>
  <div class="muted">Updated {status.get('now')}</div>
  <div class="card">
    <div class="title">Latest Run</div>
    <div>run_id: {latest.get('run_id')}</div>
    <div>strategy: {latest.get('strategy')}</div>
    <div>evaluated: {latest.get('evaluated')}</div>
    <div>best_candidate: {latest.get('best_candidate_id')}</div>
    <div>best_score: {latest.get('best_score')}</div>
  </div>
  <div class="grid">
    <div>
      <div class="title">Active Candidates</div>
      {active_html}
    </div>
    <div>
      <div class="title">Recent Evaluations</div>
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
