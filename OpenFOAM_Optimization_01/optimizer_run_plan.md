# Optimization Run Plan (OpenFOAM + OpenVSP)

This plan is designed for the current pipeline state:
- `mesh_cores = 8`
- `simpleFoam` runs in parallel after `decomposePar`
- solver default runtime is now `400` iterations (`endTime=400`)
- stale snappy-generated `0/` fields are cleaned before solver decomposition

## Environment (WSL)

Run all commands from a WSL shell:

```bash
cd /home/jwhite/JWsim/OpenFOAM_Optimization_01
source /opt/openfoam10/etc/bashrc
```

## Stage 0: Smoke Test (Single Sweep, Known Design)

Purpose:
- Verify end-to-end pipeline after recent fixes
- Confirm no solver-stage `decomposePar` crash
- Confirm all alpha cases produce `results.json`

Command:

```bash
bash scripts/run_sweep.sh \
  --start 0 --end 8 --step 2 \
  --end-time 400 \
  --uinf 25 \
  --averaging-window 50 \
  --mesh-cores 8 \
  --case-prefix alpha_smoke \
  --case-suffix sweep \
  --des-file geometry/source/iterations/iter_0003.des
```

Quick checks:

```bash
find cases/test_runs -maxdepth 2 -type f -path '*/alpha_smoke_*_sweep/results.json'
```

```bash
python3 scripts/tail_raw_output.py --path cases/test_runs/alpha_smoke_0_sweep/log.snappyHexMesh.auto --from-start --show-file
```

```bash
python3 scripts/tail_raw_output.py --path cases/test_runs/alpha_smoke_0_sweep/log.simpleFoam.auto --from-start --show-file
```

## Stage 1: Micro DOE (3 Candidates)

Purpose:
- Validate optimizer end-to-end
- Confirm candidate outputs differ (L/D curves, refs, scores)
- Catch failures cheaply before long runs

Command:

```bash
python3 scripts/run_optimizer.py --n-samples 3 --mesh-cores 8 --run-id doe3_smoke
```

Check results:

```bash
cat results/optimizer_runs/doe3_smoke/summary.json
```

What to confirm:
- No `solver_fail`
- `score_total` populated for all candidates
- `best_candidate_id` is set

## Stage 2: Broad DOE (20 Candidates)

Purpose:
- Build a broad view of the design space
- Identify promising regions before refinement

Command:

```bash
python3 scripts/run_optimizer.py --n-samples 20 --mesh-cores 8 --run-id doe20_e400
```

Optional (cache enabled):

```bash
python3 scripts/run_optimizer.py --n-samples 20 --mesh-cores 8 --run-id doe20_e400 --use-cache
```

Monitor live:

```bash
python3 scripts/tail_raw_output.py --latest --from-start --show-file
```

Dashboard:

```bash
python3 scripts/monitor_dashboard.py --latest --refresh 5
```

## Stage 3: Seeded Differential Evolution (Refinement)

Purpose:
- Exploit the best DOE region instead of continuing random search

Command:

```bash
python3 scripts/run_optimizer.py \
  --strategy de \
  --mesh-cores 8 \
  --run-id de_from_doe20 \
  --seed-summary results/optimizer_runs/doe20_e400/summary.json \
  --de-pop-size 12 \
  --de-gens 4
```

Notes:
- Keep gens modest first (`3-5`) to validate stability.
- Increase later if scores improve and failures remain low.

## Stage 4: Local Refinement Around Best Designs

Purpose:
- Fine-tune near top designs found by DOE/DE

Command:

```bash
python3 scripts/run_optimizer.py \
  --strategy local \
  --mesh-cores 8 \
  --run-id local_from_de \
  --seed-summary results/optimizer_runs/de_from_doe20/summary.json \
  --local-top-n 3 \
  --local-samples 8 \
  --local-sigma 0.05
```

## Stage 5: Robustness / Repeatability Check (Finalists)

Purpose:
- Reduce risk of selecting a noisy winner

Command (repeat top 3 candidates 3x total):

```bash
python3 scripts/run_optimizer.py \
  --n-samples 10 \
  --mesh-cores 8 \
  --run-id repeatability_check \
  --repeat-top 3 \
  --repeat-count 3
```

Alternative:
- Re-run the best candidate sweep manually with `--end-time 500` or `600`
- Increase `--averaging-window` if the tail is still noisy

## Decision Gates (Recommended)

Before moving to the next stage, confirm:

1. No solver-stage `decomposePar` failures
2. `Aref`, `lRef`, `CofR` change across different candidates
3. L/D curves differ across candidates (not identical everywhere)
4. `summary.json` contains valid `score_total` values
5. Quasi-steady rate is acceptable at `endTime=400` (or plan a targeted runtime increase)

## Common Commands (Ops Cheatsheet)

Run a single candidate sweep:

```bash
bash scripts/run_sweep.sh \
  --start 0 --end 8 --step 2 \
  --end-time 400 \
  --uinf 25 \
  --averaging-window 50 \
  --mesh-cores 8 \
  --case-prefix alpha_test \
  --case-suffix sweep \
  --des-file geometry/source/iterations/iter_0003.des
```

Tail current run raw output:

```bash
python3 scripts/tail_raw_output.py --latest --from-start --show-file
```

Tail specific meshing log:

```bash
python3 scripts/tail_raw_output.py --path cases/test_runs/alpha_test_0_sweep/log.snappyHexMesh.auto --from-start --show-file
```

Tail specific solver log:

```bash
python3 scripts/tail_raw_output.py --path cases/test_runs/alpha_test_0_sweep/log.simpleFoam.auto --from-start --show-file
```

Check active OpenFOAM version:

```bash
echo $WM_PROJECT_VERSION
```
