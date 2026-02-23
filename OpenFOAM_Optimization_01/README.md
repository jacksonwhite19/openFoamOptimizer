# OpenFOAM Optimization Workflow

## Prereqs
- OpenFOAM 10 installed in WSL (`/opt/openfoam10/etc/bashrc`).
- OpenVSP installed on Windows.
- WSL drive mapping for Windows paths (default expects `Z:` → `\\wsl.localhost\\Ubuntu-22.04\\home`).

## Standard Workflow (Normal Operation)
1) Evaluate a single candidate (DES + sweep + score):
```bash
python3 scripts/evaluate_candidate.py --candidate-id iter_0001 --design-json designs/example_design_iter001.json
```

2) Run a DOE optimizer batch (Stage A):
```bash
python3 scripts/run_optimizer.py --n-samples 10 --seed 123 --use-cache --purge-cases --purge-keep-logs
```

3) Resume a DOE run if interrupted:
```bash
python3 scripts/run_optimizer.py --run-id 20260222_153621 --resume --n-samples 10 --seed 123 --use-cache
```

4) Validate top candidates at higher fidelity:
```bash
python3 scripts/validate_top_candidates.py --summary-json results/optimizer_runs/20260222_153621/summary.json --top-n 5 --alpha-step 2 --end-time 500 --averaging-window 100
```

5) Generate the final report (best design + histories + polars):
```bash
python3 scripts/generate_optimizer_report.py --summary-json results/optimizer_runs/20260222_153621/summary.json --top-n 5
```

## Live Monitor (Ngrok)
Start the dashboard in WSL:
```bash
python3 scripts/monitor_dashboard.py --port 8000
```
Expose it from Windows:
```bat
ngrok http 8000
```

## Raw Log Tail
Follow raw log output across phases/iterations/sweeps:
```bash
python3 scripts/tail_raw_output.py --latest
```

Follow a specific run or case:
```bash
python3 scripts/tail_raw_output.py --run-id 20260222_171452
python3 scripts/tail_raw_output.py --path cases/test_runs/alpha_8_parallel_test
```

Include existing content from the start:
```bash
python3 scripts/tail_raw_output.py --latest --from-start
```
## Common Utilities
Single sweep (0→12 deg, step 3, endTime 300):
```bash
bash scripts/run_sweep.sh --step 3
```

Export/setup only (no meshing/solver):
```bash
python3 scripts/run_single_alpha.py --alpha 8 --case-name alpha_8_export_only --no-mesh
```
