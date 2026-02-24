#!/usr/bin/env python3
"""
Stage-A optimizer driver: DOE-style random search using evaluate_candidate.py.

This is intentionally simple and robust:
- Samples mapped design variables within bounds
- Evaluates each candidate via scripts/evaluate_candidate.py
- Tracks objective history and best candidate
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OptConfig:
    problem_file: Path
    run_id: str
    n_samples: int
    seed: int | None
    output_root: Path
    use_cache: bool
    purge_cases: bool
    purge_keep_logs: bool
    patience: int
    include_pending: bool
    repeat_top: int
    repeat_count: int
    robust_k: float
    mesh_cores: int
    strategy: str
    seed_summary: Path | None
    seed_top_n: int
    de_pop_size: int
    de_gens: int
    de_f: float
    de_cr: float
    local_top_n: int
    local_samples: int
    local_sigma: float
    resume: bool
    dry_run: bool

    @property
    def run_dir(self) -> Path:
        return self.output_root / self.run_id


def local_now() -> datetime:
    """Timezone-aware local system time."""
    return datetime.now().astimezone()


def parse_args() -> OptConfig:
    parser = argparse.ArgumentParser(description="DOE optimizer driver (Stage A).")
    parser.add_argument(
        "--problem-file",
        type=Path,
        default=Path("optimization_problem_definition.json"),
        help="Optimization problem definition JSON.",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Run identifier (default: timestamp).",
    )
    parser.add_argument(
        "--n-samples",
        type=int,
        default=10,
        help="Number of random samples to evaluate.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("results/optimizer_runs"),
        help="Root output directory for optimizer runs.",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Reuse cached evaluation for duplicate designs.",
    )
    parser.add_argument(
        "--purge-cases",
        action="store_true",
        help="Delete heavy case directories after scoring.",
    )
    parser.add_argument(
        "--purge-keep-logs",
        action="store_true",
        help="Keep case logs if --purge-cases is set.",
    )
    parser.add_argument(
        "--patience",
        type=int,
        default=0,
        help="Stop after N evaluations without improvement (0 = disabled).",
    )
    parser.add_argument(
        "--repeat-top",
        type=int,
        default=0,
        help="Re-evaluate top N candidates to reduce noise (0 = disabled).",
    )
    parser.add_argument(
        "--repeat-count",
        type=int,
        default=2,
        help="Number of total evaluations per top candidate (including first).",
    )
    parser.add_argument(
        "--robust-k",
        type=float,
        default=1.0,
        help="Robust ranking coefficient: score_robust = mean - k*std.",
    )
    parser.add_argument(
        "--mesh-cores",
        type=int,
        default=8,
        help="Parallel snappyHexMesh cores for candidates (default: 8).",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default="doe",
        choices=["doe", "de", "local"],
        help="Optimization strategy: doe (random), de (differential evolution), local (local refinement).",
    )
    parser.add_argument(
        "--seed-summary",
        type=Path,
        default=None,
        help="Optional summary.json to seed DE/local strategies with top designs.",
    )
    parser.add_argument(
        "--seed-top-n",
        type=int,
        default=5,
        help="Number of top designs to use from seed summary.",
    )
    parser.add_argument(
        "--de-pop-size",
        type=int,
        default=12,
        help="DE population size.",
    )
    parser.add_argument(
        "--de-gens",
        type=int,
        default=5,
        help="DE generations.",
    )
    parser.add_argument(
        "--de-f",
        type=float,
        default=0.8,
        help="DE mutation factor (F).",
    )
    parser.add_argument(
        "--de-cr",
        type=float,
        default=0.9,
        help="DE crossover probability (CR).",
    )
    parser.add_argument(
        "--local-top-n",
        type=int,
        default=3,
        help="Top N seeds for local refinement.",
    )
    parser.add_argument(
        "--local-samples",
        type=int,
        default=8,
        help="Local samples per seed.",
    )
    parser.add_argument(
        "--local-sigma",
        type=float,
        default=0.1,
        help="Local search sigma as fraction of variable range.",
    )
    parser.add_argument(
        "--include-pending",
        action="store_true",
        help="Include variables with mapping_status != mapped.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an existing run-id (skip completed candidates).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing.",
    )
    args = parser.parse_args()

    if args.resume and args.run_id is None:
        raise RuntimeError("--resume requires --run-id to be set.")
    run_id = args.run_id or local_now().strftime("%Y%m%d_%H%M%S")
    return OptConfig(
        problem_file=args.problem_file,
        run_id=run_id,
        n_samples=args.n_samples,
        seed=args.seed,
        output_root=args.output_root,
        use_cache=args.use_cache,
        purge_cases=args.purge_cases,
        purge_keep_logs=args.purge_keep_logs,
        patience=args.patience,
        include_pending=args.include_pending,
        repeat_top=args.repeat_top,
        repeat_count=args.repeat_count,
        robust_k=args.robust_k,
        mesh_cores=args.mesh_cores,
        strategy=args.strategy,
        seed_summary=args.seed_summary,
        seed_top_n=args.seed_top_n,
        de_pop_size=args.de_pop_size,
        de_gens=args.de_gens,
        de_f=args.de_f,
        de_cr=args.de_cr,
        local_top_n=args.local_top_n,
        local_samples=args.local_samples,
        local_sigma=args.local_sigma,
        resume=args.resume,
        dry_run=args.dry_run,
    )


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    return json.loads(path.read_text())


def select_variables(problem: dict[str, Any], include_pending: bool) -> list[dict[str, Any]]:
    vars_all = problem.get("design_variables", [])
    if include_pending:
        return vars_all
    return [v for v in vars_all if v.get("mapping_status") == "mapped"]


def sample_design(variables: list[dict[str, Any]], rng: random.Random) -> dict[str, float]:
    payload: dict[str, float] = {}
    for v in variables:
        name = v["name"]
        lo = float(v["min"])
        hi = float(v["max"])
        payload[name] = lo + (hi - lo) * rng.random()
    return payload


def write_design_json(path: Path, design: dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(design, indent=2))


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def filter_design(variables: list[dict[str, Any]], design: dict[str, Any]) -> dict[str, float]:
    payload = {}
    for v in variables:
        name = v["name"]
        if name in design:
            payload[name] = float(design[name])
    return payload


def load_seed_designs(
    summary_path: Path, variables: list[dict[str, Any]], top_n: int
) -> list[dict[str, float]]:
    summary = read_json(summary_path)
    run_id = summary.get("run_id")
    if not run_id:
        return []
    run_dir = Path("results/optimizer_runs") / run_id
    entries = [s for s in summary.get("summary", []) if s.get("score_total") is not None]
    entries.sort(key=lambda r: r["score_total"], reverse=True)
    seeds = []
    for entry in entries[:top_n]:
        candidate_id = entry["candidate_id"]
        design_path = run_dir / "designs" / f"{candidate_id}.json"
        if design_path.exists():
            design_payload = read_json(design_path)
            seeds.append(filter_design(variables, design_payload))
    return seeds


def evaluate_design(
    cfg: OptConfig,
    candidate_id: str,
    design: dict[str, float],
    summary: list[dict[str, Any]],
) -> tuple[float | None, str, Path, bool]:
    design_json = cfg.run_dir / "designs" / f"{candidate_id}.json"
    if not design_json.exists():
        write_design_json(design_json, design)
    evaluation_path = cfg.run_dir / candidate_id / "evaluation.json"
    resumed = False
    if cfg.resume and evaluation_path.exists():
        score, status = parse_score(evaluation_path)
        resumed = True
    else:
        evaluation_path = run_candidate(cfg, candidate_id, design_json)
        score, status = parse_score(evaluation_path)
    summary.append(
        {
            "candidate_id": candidate_id,
            "score_total": score,
            "status": status,
            "evaluation_json": str(evaluation_path),
            "repeat_scores": [score] if score is not None else [],
            "resumed": resumed,
        }
    )
    return score, status, evaluation_path, resumed


def list_existing_designs(run_dir: Path) -> dict[str, Path]:
    designs_dir = run_dir / "designs"
    if not designs_dir.exists():
        return {}
    return {p.stem: p for p in designs_dir.glob("iter_*.json")}


def advance_rng(rng: random.Random, num_vars: int, count: int) -> None:
    for _ in range(count * num_vars):
        rng.random()


def run_candidate(cfg: OptConfig, candidate_id: str, design_json: Path) -> Path:
    cmd = [
        "python3",
        "scripts/evaluate_candidate.py",
        "--candidate-id",
        candidate_id,
        "--design-json",
        str(design_json),
        "--run-id",
        cfg.run_id,
        "--mesh-cores",
        str(cfg.mesh_cores),
    ]
    if cfg.use_cache:
        cmd.append("--use-cache")
    if cfg.purge_cases:
        cmd.append("--purge-cases")
    if cfg.purge_keep_logs:
        cmd.append("--purge-keep-logs")
    if cfg.dry_run:
        print("[dry-run] " + " ".join(cmd))
        return cfg.run_dir / candidate_id / "evaluation.json"

    log_path = cfg.run_dir / candidate_id / "log.run_candidate.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log_file:
        proc = subprocess.run(cmd, stdout=log_file, stderr=subprocess.STDOUT, text=True, check=False)
    if proc.returncode != 0:
        # evaluate_candidate writes evaluation.json on failure; we still proceed.
        return cfg.run_dir / candidate_id / "evaluation.json"
    return cfg.run_dir / candidate_id / "evaluation.json"


def parse_score(evaluation_json: Path) -> tuple[float | None, str]:
    if not evaluation_json.exists():
        return None, "missing_eval"
    payload = json.loads(evaluation_json.read_text())
    evaluation = payload.get("evaluation", {})
    status = evaluation.get("status", "unknown")
    score = evaluation.get("objective", {}).get("score_total")
    if score is None:
        return None, status
    return float(score), status


def mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    m = sum(values) / len(values)
    var = sum((v - m) ** 2 for v in values) / len(values)
    return m, var ** 0.5


def main() -> None:
    cfg = parse_args()
    problem = read_json(cfg.problem_file)
    variables = select_variables(problem, cfg.include_pending)
    if not variables:
        raise RuntimeError("No design variables selected for sampling.")

    rng = random.Random(cfg.seed)
    run_dir_exists = cfg.run_dir.exists()
    if cfg.resume and not run_dir_exists:
        raise RuntimeError(f"Resume requested but run directory is missing: {cfg.run_dir}")
    cfg.run_dir.mkdir(parents=True, exist_ok=True)

    existing_designs = list_existing_designs(cfg.run_dir) if cfg.resume else {}

    if cfg.resume and cfg.seed is not None and existing_designs:
        indices = []
        for candidate_id in existing_designs:
            try:
                indices.append(int(candidate_id.split("_")[1]))
            except (IndexError, ValueError):
                continue
        max_idx = max(indices) if indices else 0
        advance_rng(rng, len(variables), max_idx)

    summary: list[dict[str, Any]] = []
    best_score = None
    best_id = None
    no_improve = 0

    start = time.monotonic()
    if cfg.strategy == "doe":
        for i in range(cfg.n_samples):
            candidate_id = f"iter_{i+1:04d}"
            design = sample_design(variables, rng)
            score, status, _, _ = evaluate_design(cfg, candidate_id, design, summary)

            if score is not None and (best_score is None or score > best_score):
                best_score = score
                best_id = candidate_id
                no_improve = 0
            else:
                no_improve += 1

            if cfg.patience > 0 and no_improve >= cfg.patience:
                break
    elif cfg.strategy == "de":
        seeds = load_seed_designs(cfg.seed_summary, variables, cfg.seed_top_n) if cfg.seed_summary else []
        pop_size = max(cfg.de_pop_size, len(seeds))
        population: list[dict[str, float]] = []
        for seed in seeds:
            population.append(seed)
        while len(population) < pop_size:
            population.append(sample_design(variables, rng))

        pop_scores: list[float | None] = []
        for i, design in enumerate(population):
            candidate_id = f"de_g0_{i+1:03d}"
            score, _, _, _ = evaluate_design(cfg, candidate_id, design, summary)
            pop_scores.append(score)

        for gen in range(1, cfg.de_gens + 1):
            for i in range(pop_size):
                indices = list(range(pop_size))
                indices.remove(i)
                a, b, c = rng.sample(indices, 3)
                base = population[a]
                diff1 = population[b]
                diff2 = population[c]
                trial = {}
                for v in variables:
                    name = v["name"]
                    lo = float(v["min"])
                    hi = float(v["max"])
                    mutant = base[name] + cfg.de_f * (diff1[name] - diff2[name])
                    trial[name] = clamp(mutant, lo, hi)

                target = population[i]
                offspring = {}
                force_idx = rng.randrange(len(variables))
                for j, v in enumerate(variables):
                    name = v["name"]
                    if rng.random() < cfg.de_cr or j == force_idx:
                        offspring[name] = trial[name]
                    else:
                        offspring[name] = target[name]

                candidate_id = f"de_g{gen}_{i+1:03d}"
                score, _, _, _ = evaluate_design(cfg, candidate_id, offspring, summary)
                target_score = pop_scores[i]
                if score is not None and (target_score is None or score > target_score):
                    population[i] = offspring
                    pop_scores[i] = score
                if score is not None and (best_score is None or score > best_score):
                    best_score = score
                    best_id = candidate_id
    elif cfg.strategy == "local":
        if cfg.seed_summary is None:
            raise RuntimeError("--strategy local requires --seed-summary")
        seeds = load_seed_designs(cfg.seed_summary, variables, cfg.local_top_n)
        if not seeds:
            raise RuntimeError("No seed designs found for local refinement.")
        for s_idx, seed in enumerate(seeds, start=1):
            base = seed
            base_id = f"local_seed{s_idx:02d}_base"
            base_score, _, _, _ = evaluate_design(cfg, base_id, base, summary)
            best_local = base
            best_local_score = base_score
            for j in range(cfg.local_samples):
                trial = {}
                for v in variables:
                    name = v["name"]
                    lo = float(v["min"])
                    hi = float(v["max"])
                    span = hi - lo
                    perturb = rng.gauss(0.0, cfg.local_sigma * span)
                    trial[name] = clamp(base[name] + perturb, lo, hi)
                candidate_id = f"local_seed{s_idx:02d}_{j+1:02d}"
                score, _, _, _ = evaluate_design(cfg, candidate_id, trial, summary)
                if score is not None and (best_local_score is None or score > best_local_score):
                    best_local_score = score
                    best_local = trial
            if best_local_score is not None and (best_score is None or best_local_score > best_score):
                best_score = best_local_score
                best_id = f"local_seed{s_idx:02d}_best"
                evaluate_design(cfg, best_id, best_local, summary)

    elapsed = time.monotonic() - start

    # Optional re-evaluation of top candidates to reduce noise.
    if cfg.repeat_top > 0 and cfg.repeat_count > 1:
        ranked = [s for s in summary if s["score_total"] is not None]
        ranked.sort(key=lambda r: r["score_total"], reverse=True)
        for entry in ranked[: cfg.repeat_top]:
            base_id = entry["candidate_id"]
            design_json = cfg.run_dir / "designs" / f"{base_id}.json"
            for j in range(1, cfg.repeat_count):
                repeat_id = f"{base_id}_r{j+1}"
                evaluation_path = run_candidate(cfg, repeat_id, design_json)
                score, status = parse_score(evaluation_path)
                if score is not None:
                    entry["repeat_scores"].append(score)
                entry.setdefault("repeat_ids", []).append(repeat_id)
                entry.setdefault("repeat_status", []).append(status)

        # Compute robust scores
        for entry in summary:
            scores = [s for s in entry.get("repeat_scores", []) if s is not None]
            if not scores:
                entry["score_mean"] = None
                entry["score_std"] = None
                entry["score_robust"] = None
                continue
            m, s = mean_std(scores)
            entry["score_mean"] = m
            entry["score_std"] = s
            entry["score_robust"] = m - cfg.robust_k * s

        # Update best candidate with robust score if available
        robust_ranked = [s for s in summary if s.get("score_robust") is not None]
        if robust_ranked:
            robust_ranked.sort(key=lambda r: r["score_robust"], reverse=True)
            best_id = robust_ranked[0]["candidate_id"]
            best_score = robust_ranked[0]["score_robust"]
    summary_out = cfg.run_dir / "summary.json"
    summary_payload = {
        "run_id": cfg.run_id,
        "n_samples": cfg.n_samples,
        "evaluated": len(summary),
        "best_candidate_id": best_id,
        "best_score": best_score,
        "robust_k": cfg.robust_k,
        "repeat_top": cfg.repeat_top,
        "repeat_count": cfg.repeat_count,
        "strategy": cfg.strategy,
        "strategy_params": {
            "de_pop_size": cfg.de_pop_size,
            "de_gens": cfg.de_gens,
            "de_f": cfg.de_f,
            "de_cr": cfg.de_cr,
            "local_top_n": cfg.local_top_n,
            "local_samples": cfg.local_samples,
            "local_sigma": cfg.local_sigma,
            "seed_summary": str(cfg.seed_summary) if cfg.seed_summary else None,
            "seed_top_n": cfg.seed_top_n,
            "mesh_cores": cfg.mesh_cores,
        },
        "elapsed_sec": round(elapsed, 2),
        "summary": summary,
    }
    if not cfg.dry_run:
        summary_out.write_text(json.dumps(summary_payload, indent=2))
        print(f"Wrote optimizer summary: {summary_out}")
    else:
        print("[dry-run] wrote optimizer summary: " + str(summary_out))


if __name__ == "__main__":
    main()
