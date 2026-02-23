# Transition Plan: Single-Sweep Pipeline to Full Optimizer

Last updated: 2026-02-22

## 1. Objective
Move from a manually-triggered alpha sweep to a robust, autonomous optimization loop that:
- generates candidate geometry,
- runs CFD evaluation consistently,
- scores candidates with mission-relevant metrics,
- converges to a high-performing, stable design.

## 2. Current State (Starting Point)
- `scripts/run_single_alpha.py` performs end-to-end single-angle evaluation.
- `scripts/run_sweep.sh` runs a multi-alpha sweep and currently supports mesh reuse within a sweep.
- `results.json` is produced per case with CL/CD/CM summary and mesh-quality fields.
- Geometry exports (STL, massprops, frontal area) are now automated.

## 3. Target End State
- One command launches optimizer iterations (no manual intervention).
- Each candidate returns a single `evaluation.json` with objective, constraints, and metadata.
- Failures are handled deterministically (retry/penalty/skip).
- Top designs are re-run at higher fidelity before final selection.

## 4. Guiding Principles for Best Optimization Results
- Keep normalization and references fixed across all iterations (`Aref`, `lRef`, `rho`, `Uinf`, alpha definitions).
- Optimize on smooth aggregated metrics, not single noisy points.
- Separate exploration from exploitation (global search first, local refinement later).
- Penalize unstable or low-confidence runs instead of silently accepting them.
- Validate the top candidates with stricter settings before declaring a winner.

## 5. Step-by-Step Execution Plan

## Phase 0 - Lock the Baseline and Evaluation Contract
- `[ ]` Define canonical run configuration in one location (`optimization_params.json`).
- `[ ]` Freeze sweep definition for optimization (example: alpha `0,3,6,9,12`, `endTime=300`).
- `[ ]` Freeze mesh policy for optimization (`mesh once per candidate, reuse for remaining alphas`).
- `[ ]` Freeze objective/constraint schema and version it (`schema_version` in outputs).
- `[ ]` Add a baseline reproducibility check: run same candidate 3 times and record variation.

Done when:
- Same input design returns near-identical score and constraints within agreed tolerances.

## Phase 1 - Formalize the Optimization Problem
- `[x]` Finalize design variable list with hard bounds and units.
- `[x]` Add geometry sanity constraints before CFD (e.g., span/chord positivity, DES write validity).
- `[x]` Define objective function explicitly (example):
  `maximize mean(L/D across sweep) - penalties`.
- `[x]` Define penalties for:
  mesh quality warnings,
  solver non-convergence,
  unstable force statistics,
  infeasible geometry.
- `[x]` Define mission-weighted scoring option (weights by expected operating alpha).

Implemented in:
- `optimization_problem_definition.json`
- `scripts/score_sweep_results.py`
- `scripts/generate_iteration_des.py`
- `optimization_params.json` (runtime linkage)

Done when:
- A single function `score = f(results_over_alphas, constraints)` is documented and deterministic.

## Phase 2 - Build a Candidate Evaluator API
- `[x]` Create `scripts/evaluate_candidate.py` as the only evaluator entry point.
- `[x]` Inputs:
  `candidate_id`, design vector, run config, optional seed.
- `[x]` Outputs:
  `results/optimizer_runs/<run_id>/iter_<n>/evaluation.json`.
- `[x]` Evaluator flow:
  1. apply design variables to VSP/DES,
  2. run first alpha full pipeline,
  3. run remaining alphas with mesh reuse,
  4. aggregate per-alpha `results.json`,
  5. compute objective + constraints + pass/fail flags.
- `[x]` Add strict status codes:
  `ok`, `geometry_fail`, `mesh_fail`, `solver_fail`, `post_fail`, `timeout`.

Done when:
- Any candidate evaluation returns a structured JSON even on failure.

## Phase 3 - Data and Artifact Management
- `[x]` Standardize run directory layout:
  `results/optimizer_runs/<timestamp_or_run_id>/iter_0001/...`
- `[x]` Save per-iteration metadata:
  git commit hash,
  config snapshot,
  variable vector,
  wall-clock timings,
  objective breakdown.
- `[x]` Add lightweight artifact retention policy:
  keep `evaluation.json`, logs, final force files;
  optionally purge heavy transient fields after scoring.
- `[x]` Add cache key for duplicate designs (hash vector + config), with cache hit reuse.

Done when:
- You can fully reconstruct any score from saved artifacts.

## Phase 4 - Optimizer Driver
- `[x]` Create `scripts/run_optimizer.py` driver.
- `[x]` Implement staged strategy for best results:
  Stage A: space-filling DOE (20-50 points) implemented,
  Stage B: global optimizer (differential evolution) implemented,
  Stage C: local refinement on top 3-5 designs implemented.
- `[x]` Add hard iteration budget and stop criteria:
  no improvement over N iterations,
  max evaluations,
  wall-time cap.
- `[x]` Add failure-aware candidate handling:
  retries (limited),
  fallback penalties,
  blacklist truly invalid regions.

Done when:
- One command completes multi-iteration optimization and returns ranked candidates.

## Phase 5 - Convergence and Noise Controls
- `[x]` Keep averaging window fixed (currently last 50 samples) for all optimization runs.
- `[x]` Add force stability checks:
  relative std thresholds for CL/CD/CM.
- `[x]` Add optional re-evaluation of promising candidates (2nd pass) to reduce stochastic ranking errors.
- `[x]` Use robust ranking score for finals:
  `score_robust = mean_score - k * std_score`.

Done when:
- Ranking of top candidates is stable under repeat runs.

## Phase 6 - High-Fidelity Validation Gate (Before Final Decision)
- `[x]` Add a validation script to re-run top 5-10 candidates with stricter settings:
  finer alpha sweep (example: 2 deg increments),
  longer solver horizon (example: `endTime=400/500`),
  optional tighter mesh controls if runtime allows.
- `[ ]` Execute the high-fidelity validation run on top candidates.
- `[ ]` Compare low-fidelity optimizer ranking vs high-fidelity ranking.
- `[ ]` Select final winner using high-fidelity objective and constraints only.

Done when:
- Final selected design remains top-performing under validation settings.

## Phase 7 - Operational Readiness
- `[x]` Add restart/resume from last completed iteration.
- `[x]` Add summary report generator:
  best design variables,
  objective history,
  constraint history,
  alpha-polars for top candidates.
- `[x]` Add a single README command sequence for normal operation.
- `[x]` Add live monitoring dashboard (local + ngrok).

Done when:
- Another user can run and resume optimization without ad-hoc manual steps.

## 6. Immediate Next Tasks (Recommended Order)
- `[x]` Implement `evaluate_candidate.py` and standardized `evaluation.json`.
- `[x]` Define and freeze objective/penalty formula in code.
- `[~]` Implement `run_optimizer.py` with DOE + global search stage (DOE done, global search pending).
- `[x]` Add cache + retry + timeout controls.
- `[ ]` Run a 10-iteration smoke test and inspect failure modes.

## 7. Suggested `evaluation.json` Schema
```json
{
  "schema_version": "1.0",
  "candidate_id": "iter_0001",
  "design_variables": {},
  "alphas_deg": [0, 3, 6, 9, 12],
  "per_alpha": [],
  "objective": {
    "score_total": 0.0,
    "score_components": {},
    "penalties": {}
  },
  "constraints": {
    "feasible": true,
    "violations": []
  },
  "status": "ok",
  "timing_sec": {
    "geometry": 0.0,
    "mesh": 0.0,
    "solver": 0.0,
    "total": 0.0
  },
  "artifacts": {}
}
```

## 8. Default Optimization Settings (Initial)
- Sweep alphas: `0, 3, 6, 9, 12`
- Sweep step: `3 deg`
- Solver end time: `300`
- Mesh policy: `first alpha meshes, remaining alphas reuse mesh`
- Force averaging window: `50`
- Mesh gates: keep current numeric thresholds; penalize warnings instead of immediate hard fail unless catastrophic
