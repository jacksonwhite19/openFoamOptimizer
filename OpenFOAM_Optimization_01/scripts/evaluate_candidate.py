#!/usr/bin/env python3
"""
Evaluate a single candidate design:
1) Generate iteration DES (baseline -> new .des)
2) Run alpha sweep (mesh once, reuse)
3) Score sweep results and write evaluation.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import hashlib
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def local_now() -> datetime:
    """Timezone-aware local system time."""
    return datetime.now().astimezone()


@dataclass(frozen=True)
class EvalConfig:
    candidate_id: str
    design_json: Path
    problem_file: Path
    base_des: Path
    des_output: Path
    run_id: str
    results_root: Path
    sweep_script: Path
    cases_root: Path
    case_prefix: str
    case_suffix: str
    alpha_start: int
    alpha_end: int
    alpha_step: int
    end_time: int
    uinf: float
    averaging_window: int
    mesh_cores: int
    dry_run: bool
    wsl_root: str
    use_cache: bool
    cache_index: Path
    cache_salt: str | None
    purge_cases: bool
    purge_keep_logs: bool
    sweep_retries: int
    timeout_sweep_sec: int | None

    @property
    def output_dir(self) -> Path:
        return self.results_root / self.run_id / self.candidate_id


def parse_args() -> EvalConfig:
    parser = argparse.ArgumentParser(description="Evaluate a candidate design end-to-end.")
    parser.add_argument("--candidate-id", required=True, help="Candidate identifier (e.g., iter_0001)")
    parser.add_argument("--design-json", type=Path, required=True, help="Design variable values JSON")
    parser.add_argument(
        "--problem-file",
        type=Path,
        default=Path("optimization_problem_definition.json"),
        help="Optimization problem definition JSON",
    )
    parser.add_argument(
        "--base-des",
        type=Path,
        default=Path("geometry/source/baseline.des"),
        help="Baseline DES (read-only)",
    )
    parser.add_argument(
        "--des-output",
        type=Path,
        default=None,
        help="Output DES file for this candidate (default: geometry/source/iterations/<candidate>.des)",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Run group ID (default: timestamp)",
    )
    parser.add_argument(
        "--results-root",
        type=Path,
        default=Path("results/optimizer_runs"),
        help="Root directory for evaluation outputs",
    )
    parser.add_argument(
        "--sweep-script",
        type=Path,
        default=Path("scripts/run_sweep.sh"),
        help="Sweep script to execute",
    )
    parser.add_argument(
        "--cases-root",
        type=Path,
        default=Path("cases/test_runs"),
        help="Root where sweep cases are generated",
    )
    parser.add_argument("--case-prefix", type=str, default=None, help="Case name prefix")
    parser.add_argument("--case-suffix", type=str, default="sweep", help="Case name suffix")
    parser.add_argument("--alpha-start", type=int, default=None, help="Sweep start alpha")
    parser.add_argument("--alpha-end", type=int, default=None, help="Sweep end alpha")
    parser.add_argument("--alpha-step", type=int, default=None, help="Sweep step (2 or 3)")
    parser.add_argument("--end-time", type=int, default=None, help="Solver endTime")
    parser.add_argument("--uinf", type=float, default=None, help="Freestream velocity")
    parser.add_argument("--averaging-window", type=int, default=None, help="Force averaging window")
    parser.add_argument("--mesh-cores", type=int, default=None, help="Parallel snappyHexMesh cores")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    parser.add_argument(
        "--wsl-root",
        type=str,
        default="/home/jwhite/JWsim/OpenFOAM_Optimization_01",
        help="WSL project root for running sweep when invoked from Windows.",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Reuse prior evaluation if the cache key matches.",
    )
    parser.add_argument(
        "--cache-index",
        type=Path,
        default=Path("results/optimizer_runs/cache_index.json"),
        help="Cache index JSON file.",
    )
    parser.add_argument(
        "--cache-salt",
        type=str,
        default=None,
        help="Optional string to force cache key changes (e.g., code version).",
    )
    parser.add_argument(
        "--purge-cases",
        action="store_true",
        help="Delete heavy case directories after scoring (keeps evaluation + logs).",
    )
    parser.add_argument(
        "--purge-keep-logs",
        action="store_true",
        help="If set, keep log files from cases before deleting the case directory.",
    )
    parser.add_argument(
        "--sweep-retries",
        type=int,
        default=0,
        help="Retry the sweep command up to N times on failure.",
    )
    parser.add_argument(
        "--timeout-sweep",
        type=int,
        default=None,
        help="Timeout in seconds for the sweep command (None = no timeout).",
    )
    args = parser.parse_args()

    run_id = args.run_id or local_now().strftime("%Y%m%d_%H%M%S")
    case_prefix = args.case_prefix or args.candidate_id

    des_output = args.des_output
    if des_output is None:
        des_output = Path("geometry/source/iterations") / f"{args.candidate_id}.des"

    return EvalConfig(
        candidate_id=args.candidate_id,
        design_json=args.design_json,
        problem_file=args.problem_file,
        base_des=args.base_des,
        des_output=des_output,
        run_id=run_id,
        results_root=args.results_root,
        sweep_script=args.sweep_script,
        cases_root=args.cases_root,
        case_prefix=case_prefix,
        case_suffix=args.case_suffix,
        alpha_start=args.alpha_start or -1,
        alpha_end=args.alpha_end or -1,
        alpha_step=args.alpha_step or -1,
        end_time=args.end_time or -1,
        uinf=args.uinf or -1.0,
        averaging_window=args.averaging_window or -1,
        mesh_cores=args.mesh_cores or -1,
        dry_run=args.dry_run,
        wsl_root=args.wsl_root,
        use_cache=args.use_cache,
        cache_index=args.cache_index,
        cache_salt=args.cache_salt,
        purge_cases=args.purge_cases,
        purge_keep_logs=args.purge_keep_logs,
        sweep_retries=args.sweep_retries,
        timeout_sweep_sec=args.timeout_sweep,
    )


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    return json.loads(path.read_text())


def compute_cache_key(problem: dict[str, Any], cfg: EvalConfig, design_payload: dict[str, Any]) -> str:
    sweep_sig = {
        "alpha_start": cfg.alpha_start,
        "alpha_end": cfg.alpha_end,
        "alpha_step": cfg.alpha_step,
        "end_time": cfg.end_time,
        "uinf": cfg.uinf,
        "averaging_window": cfg.averaging_window,
        "mesh_cores": cfg.mesh_cores,
        "case_suffix": cfg.case_suffix,
        "mesh_policy": problem.get("sweep_definition", {}).get("mesh_policy"),
    }
    payload = {
        "design": design_payload,
        "problem": problem,
        "sweep": sweep_sig,
        "cache_salt": cfg.cache_salt,
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def load_cache_index(cache_index: Path) -> dict[str, Any]:
    if not cache_index.exists():
        return {"entries": {}}
    try:
        return json.loads(cache_index.read_text())
    except json.JSONDecodeError:
        return {"entries": {}}


def write_cache_index(cache_index: Path, payload: dict[str, Any]) -> None:
    cache_index.parent.mkdir(parents=True, exist_ok=True)
    cache_index.write_text(json.dumps(payload, indent=2))


def resolve_sweep_defaults(cfg: EvalConfig, problem: dict[str, Any]) -> EvalConfig:
    sweep = problem.get("sweep_definition", {})
    alphas = sweep.get("alphas_deg", [])
    if not alphas:
        raise ValueError("Problem file has no sweep_definition.alphas_deg")
    alphas_sorted = sorted(alphas)
    diffs = {alphas_sorted[i + 1] - alphas_sorted[i] for i in range(len(alphas_sorted) - 1)}

    alpha_start = cfg.alpha_start if cfg.alpha_start >= 0 else int(alphas_sorted[0])
    alpha_end = cfg.alpha_end if cfg.alpha_end >= 0 else int(alphas_sorted[-1])

    if cfg.alpha_step >= 0:
        alpha_step = cfg.alpha_step
    elif len(diffs) == 1:
        alpha_step = int(diffs.pop())
    else:
        raise ValueError("Non-uniform alpha list; pass --alpha-start/--alpha-end/--alpha-step.")

    end_time = cfg.end_time if cfg.end_time >= 0 else int(sweep.get("solver_end_time", 300))
    uinf = cfg.uinf if cfg.uinf >= 0 else float(problem.get("flow_conditions", {}).get("u_inf", 25.0))
    averaging_window = cfg.averaging_window if cfg.averaging_window >= 0 else int(
        sweep.get("averaging_window", 50)
    )
    mesh_cores = cfg.mesh_cores if cfg.mesh_cores >= 0 else int(
        sweep.get("mesh_cores", 1)
    )

    return EvalConfig(
        candidate_id=cfg.candidate_id,
        design_json=cfg.design_json,
        problem_file=cfg.problem_file,
        base_des=cfg.base_des,
        des_output=cfg.des_output,
        run_id=cfg.run_id,
        results_root=cfg.results_root,
        sweep_script=cfg.sweep_script,
        cases_root=cfg.cases_root,
        case_prefix=cfg.case_prefix,
        case_suffix=cfg.case_suffix,
        alpha_start=alpha_start,
        alpha_end=alpha_end,
        alpha_step=alpha_step,
        end_time=end_time,
        uinf=uinf,
        averaging_window=averaging_window,
        mesh_cores=mesh_cores,
        dry_run=cfg.dry_run,
        wsl_root=cfg.wsl_root,
        use_cache=cfg.use_cache,
        cache_index=cfg.cache_index,
        cache_salt=cfg.cache_salt,
        purge_cases=cfg.purge_cases,
        purge_keep_logs=cfg.purge_keep_logs,
        sweep_retries=cfg.sweep_retries,
        timeout_sweep_sec=cfg.timeout_sweep_sec,
    )


def run_cmd(
    cmd: list[str],
    log_path: Path,
    dry_run: bool,
    stage: str,
    timeout_sec: int | None = None,
    retries: int = 0,
) -> float:
    if dry_run:
        print(f"[dry-run] {' '.join(cmd)}")
        return 0.0
    start = time.monotonic()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    attempts = max(1, retries + 1)
    for attempt in range(1, attempts + 1):
        mode = "w" if attempt == 1 else "a"
        with log_path.open(mode) as log_file:
            if attempt > 1:
                log_file.write(f"\n--- retry {attempt}/{attempts} ---\n")
            try:
                proc = subprocess.run(
                    cmd,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                    timeout=timeout_sec,
                )
            except subprocess.TimeoutExpired:
                if attempt < attempts:
                    continue
                raise RuntimeError(
                    f"[{stage}] Command timed out after {timeout_sec}s: {' '.join(cmd)}. See {log_path}"
                )
        if proc.returncode == 0:
            return time.monotonic() - start
        if attempt >= attempts:
            raise RuntimeError(
                f"[{stage}] Command failed ({proc.returncode}): {' '.join(cmd)}. See {log_path}"
            )
    return time.monotonic() - start


def fallback_failure_score(status: str) -> float:
    """Deterministic score for failed evaluations so optimizers can continue ranking."""
    # Keep these far below plausible CFD scores (~O(1)) but ordered by failure class.
    if status == "geometry_fail":
        return -900.0
    if status == "solver_fail":
        return -1000.0
    if status == "post_fail":
        return -1100.0
    return -1200.0


def main() -> None:
    cfg = parse_args()
    problem = read_json(cfg.problem_file)
    design_payload = read_json(cfg.design_json)
    cfg = resolve_sweep_defaults(cfg, problem)

    output_dir = cfg.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_key = compute_cache_key(problem, cfg, design_payload)
    cache_index = load_cache_index(cfg.cache_index)
    cache_entry = cache_index.get("entries", {}).get(cache_key)

    if cfg.use_cache and cache_entry:
        cached_eval = Path(cache_entry.get("evaluation_json", ""))
        if cached_eval.exists():
            score_out = output_dir / "evaluation.json"
            if not cfg.dry_run:
                score_out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cached_eval, score_out)
                metadata = {
                    "candidate_id": cfg.candidate_id,
                    "run_id": cfg.run_id,
                    "design_json": str(cfg.design_json),
                    "des_output": str(cfg.des_output),
                    "case_prefix": cfg.case_prefix,
                    "case_suffix": cfg.case_suffix,
                    "alpha_start": cfg.alpha_start,
                    "alpha_end": cfg.alpha_end,
                    "alpha_step": cfg.alpha_step,
                    "end_time": cfg.end_time,
                    "uinf": cfg.uinf,
                    "evaluation_json": str(score_out),
                    "status": "cached",
                    "cache_key": cache_key,
                    "cache_source": str(cached_eval),
                }
                (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
            print(f"Used cached evaluation: {cached_eval}")
            return

    status = "ok"
    error_message = None
    score_out = output_dir / "evaluation.json"

    timings = {
        "generate_des": 0.0,
        "sweep": 0.0,
        "score": 0.0,
        "total": 0.0,
    }
    total_start = time.monotonic()

    try:
        # 1) Generate iteration DES
        des_log = output_dir / "log.generate_iteration_des.txt"
        timings["generate_des"] = run_cmd(
            [
                "python3",
                "scripts/generate_iteration_des.py",
                "--base-des",
                str(cfg.base_des),
                "--output-des",
                cfg.des_output.as_posix(),
                "--problem-file",
                str(cfg.problem_file),
                "--design-json",
                str(cfg.design_json),
            ],
            des_log,
            cfg.dry_run,
            stage="geometry_fail",
        )

        # 2) Run sweep
        sweep_log = output_dir / "log.run_sweep.txt"
        sweep_cmd = [
            "bash",
            cfg.sweep_script.as_posix(),
            "--start",
            str(cfg.alpha_start),
            "--end",
            str(cfg.alpha_end),
            "--step",
            str(cfg.alpha_step),
            "--end-time",
            str(cfg.end_time),
            "--uinf",
            str(cfg.uinf),
            "--averaging-window",
            str(cfg.averaging_window),
            "--mesh-cores",
            str(cfg.mesh_cores),
            "--case-prefix",
            cfg.case_prefix,
            "--case-suffix",
            cfg.case_suffix,
            "--des-file",
            cfg.des_output.as_posix(),
        ]

        if os.name == "nt":
            sweep_shell = f"cd {cfg.wsl_root} && " + " ".join(sweep_cmd)
            timings["sweep"] = run_cmd(
                ["wsl", "-e", "bash", "-lc", sweep_shell],
                sweep_log,
                cfg.dry_run,
                stage="solver_fail",
                timeout_sec=cfg.timeout_sweep_sec,
                retries=cfg.sweep_retries,
            )
        else:
            timings["sweep"] = run_cmd(
                sweep_cmd,
                sweep_log,
                cfg.dry_run,
                stage="solver_fail",
                timeout_sec=cfg.timeout_sweep_sec,
                retries=cfg.sweep_retries,
            )

        # 3) Score sweep
        score_log = output_dir / "log.score_sweep.txt"
        timings["score"] = run_cmd(
            [
                "python3",
                "scripts/score_sweep_results.py",
                "--problem-file",
                str(cfg.problem_file),
                "--cases-root",
                str(cfg.cases_root),
                "--case-prefix",
                cfg.case_prefix,
                "--case-suffix",
                cfg.case_suffix,
                "--design-json",
                str(cfg.design_json),
                "--des-file",
                cfg.des_output.as_posix(),
                "--output-file",
                str(score_out),
            ],
            score_log,
            cfg.dry_run,
            stage="post_fail",
        )
    except RuntimeError as exc:
        msg = str(exc)
        if msg.startswith("[geometry_fail]"):
            status = "geometry_fail"
        elif msg.startswith("[solver_fail]"):
            status = "solver_fail"
        elif msg.startswith("[post_fail]"):
            status = "post_fail"
        else:
            status = "error"
        error_message = msg

    timings["total"] = time.monotonic() - total_start

    if cfg.dry_run:
        return

    # If scoring didn't run, write a minimal evaluation file.
    if not score_out.exists():
        fail_score = fallback_failure_score(status)
        fallback = {
            "problem_name": problem.get("problem_name"),
            "problem_schema_version": problem.get("schema_version"),
            "evaluation": {
                "status": status,
                "error": error_message,
                "objective": {
                    "score_total": fail_score,
                    "penalty_total": abs(fail_score),
                },
                "constraints": {
                    "feasible": False
                },
            }
        }
        score_out.write_text(json.dumps(fallback, indent=2))

    # Write a light metadata file for tracking.
    # Snapshot config files for reproducibility.
    snapshot_dir = output_dir / "config_snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    try:
        (snapshot_dir / "optimization_problem_definition.json").write_text(
            Path(cfg.problem_file).read_text()
        )
    except FileNotFoundError:
        pass
    opt_params = Path("optimization_params.json")
    if opt_params.exists():
        (snapshot_dir / "optimization_params.json").write_text(opt_params.read_text())

    git_hash = None
    git_status = None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            git_hash = proc.stdout.strip()
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            git_status = proc.stdout.strip()
    except FileNotFoundError:
        pass

    metadata = {
        "candidate_id": cfg.candidate_id,
        "run_id": cfg.run_id,
        "design_json": str(cfg.design_json),
        "des_output": str(cfg.des_output),
        "case_prefix": cfg.case_prefix,
        "case_suffix": cfg.case_suffix,
        "alpha_start": cfg.alpha_start,
        "alpha_end": cfg.alpha_end,
        "alpha_step": cfg.alpha_step,
        "end_time": cfg.end_time,
        "uinf": cfg.uinf,
        "averaging_window": cfg.averaging_window,
        "mesh_cores": cfg.mesh_cores,
        "sweep_retries": cfg.sweep_retries,
        "timeout_sweep_sec": cfg.timeout_sweep_sec,
        "evaluation_json": str(score_out),
        "status": status,
        "error": error_message,
        "timing_sec": {k: round(v, 3) for k, v in timings.items()},
        "git": {
            "commit": git_hash,
            "dirty": bool(git_status),
            "status": git_status,
        },
        "cache_key": cache_key,
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    print(f"Wrote evaluation: {score_out}")

    # Update cache index for future reuse.
    cache_index.setdefault("entries", {})
    cache_index["entries"][cache_key] = {
        "evaluation_json": str(score_out),
        "metadata_json": str(output_dir / "metadata.json"),
        "candidate_id": cfg.candidate_id,
        "run_id": cfg.run_id,
        "timestamp": local_now().isoformat(timespec="seconds"),
        "design_json": str(cfg.design_json),
        "problem_file": str(cfg.problem_file),
        "sweep": {
            "alpha_start": cfg.alpha_start,
            "alpha_end": cfg.alpha_end,
            "alpha_step": cfg.alpha_step,
            "end_time": cfg.end_time,
            "uinf": cfg.uinf,
            "averaging_window": cfg.averaging_window,
            "mesh_cores": cfg.mesh_cores,
            "sweep_retries": cfg.sweep_retries,
            "timeout_sweep_sec": cfg.timeout_sweep_sec,
        },
    }
    write_cache_index(cfg.cache_index, cache_index)

    # Optional cleanup of heavy case directories.
    if cfg.purge_cases:
        case_dirs = []
        for alpha in range(cfg.alpha_start, cfg.alpha_end + 1, cfg.alpha_step):
            case_dirs.append(cfg.cases_root / f"{cfg.case_prefix}_{alpha}_{cfg.case_suffix}")
        purge_log = output_dir / "log.purge_cases.txt"
        lines = []
        for case_dir in case_dirs:
            if not case_dir.exists():
                continue
            if cfg.purge_keep_logs:
                dest = output_dir / "case_logs" / case_dir.name
                dest.mkdir(parents=True, exist_ok=True)
                for log_file in case_dir.glob("log.*"):
                    shutil.copy2(log_file, dest / log_file.name)
            shutil.rmtree(case_dir)
            lines.append(f"Deleted {case_dir}")
        purge_log.write_text("\n".join(lines) + ("\n" if lines else ""))


if __name__ == "__main__":
    main()
