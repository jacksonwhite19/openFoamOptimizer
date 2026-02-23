## STL to Mesh Tutorial
https://youtu.be/ehDEcCVN2MI?si=ebcvVqtoEh7CuNhK

## SimpleFoam Tutorial
https://www.youtube.com/watch?v=sfFez7h0UUQ


## WSL Navigate to Folder
cd /home/jwhite/JWsim/OpenFOAM_Optimization_01

## to run vsp scripts:
"C:\Users\Jackson\Desktop\ZZ_Software Downloads\OpenVSP-3.46.0-win64\vsp.exe" -batch "Z:\home\jwhite\JWsim\OpenFOAM_Optimization_01\geometry\source\baseline.vsp3" -des "Z:\home\jwhite\JWsim\OpenFOAM_Optimization_01\geometry\source\baseline.des" -script "Z:\home\jwhite\JWsim\OpenFOAM_Optimization_01\scripts\vsp_utils\export_frontal_area.vspscript"

## Full single-alpha pipeline (export + mesh + CFD)
python3 scripts/run_single_alpha.py --alpha 8 --case-name alpha_8_full_iter001 --end-time 400

## Full single-alpha pipeline with parallel mesh (16 cores)
python3 scripts/run_single_alpha.py --alpha 8 --case-name alpha_8_full_iter001 --end-time 400 --mesh-cores 16

## Export/setup only (no meshing/solver)
python3 scripts/run_single_alpha.py --alpha 8 --case-name alpha_8_export_only --no-mesh

## Alpha sweep (0 to 12 deg, step 2, endTime 300)
bash scripts/run_sweep.sh

## Alpha sweep (0 to 12 deg, step 3, endTime 300)
bash scripts/run_sweep.sh --step 3

## Alpha sweep with parallel mesh (16 cores)
bash scripts/run_sweep.sh --step 3 --mesh-cores 16

## Score latest sweep for optimizer objective/penalties
python3 scripts/score_sweep_results.py --case-suffix sweep --output-file results/sweep_score.json

## Generate iteration DES from baseline (does not modify baseline.des)
python3 scripts/generate_iteration_des.py --output-des geometry/source/iterations/iter_0001.des --design-json designs/example_design_iter001.json

## Run one case with iteration-specific DES
python3 scripts/run_single_alpha.py --alpha 8 --case-name alpha_8_iter001 --des-file geometry/source/iterations/iter_0001.des --end-time 300

## Evaluate one candidate (DES + sweep + score)
python3 scripts/evaluate_candidate.py --candidate-id iter_0001 --design-json designs/example_design_iter001.json

## Evaluate one candidate with parallel mesh (16 cores)
python3 scripts/evaluate_candidate.py --candidate-id iter_0001 --design-json designs/example_design_iter001.json --mesh-cores 16

## Evaluate using cache (reuse if same design/config)
python3 scripts/evaluate_candidate.py --candidate-id iter_0001 --design-json designs/example_design_iter001.json --use-cache

## Evaluate and purge heavy cases after scoring (keep logs)
python3 scripts/evaluate_candidate.py --candidate-id iter_0001 --design-json designs/example_design_iter001.json --purge-cases --purge-keep-logs

## Run DOE optimizer (Stage A random search)
python3 scripts/run_optimizer.py --n-samples 10 --seed 123 --use-cache --purge-cases --purge-keep-logs

## Run DOE optimizer with parallel mesh (16 cores)
python3 scripts/run_optimizer.py --n-samples 10 --seed 123 --use-cache --purge-cases --purge-keep-logs --mesh-cores 16

## DOE with repeat evaluation for robust ranking
python3 scripts/run_optimizer.py --n-samples 10 --seed 123 --repeat-top 3 --repeat-count 3 --robust-k 1.0 --use-cache

## Resume a DOE run (skip completed candidates)
python3 scripts/run_optimizer.py --run-id 20260222_153621 --resume --n-samples 10 --seed 123 --use-cache

## Differential evolution (Stage B)
python3 scripts/run_optimizer.py --strategy de --de-pop-size 12 --de-gens 5 --seed-summary results/optimizer_runs/20260222_153621/summary.json --seed-top-n 5 --use-cache

## Local refinement (Stage C)
python3 scripts/run_optimizer.py --strategy local --seed-summary results/optimizer_runs/20260222_153621/summary.json --local-top-n 3 --local-samples 8 --local-sigma 0.1 --use-cache

## High-fidelity validation of top candidates
python3 scripts/validate_top_candidates.py --summary-json results/optimizer_runs/20260222_153621/summary.json --top-n 5 --alpha-step 2 --end-time 500 --averaging-window 100

## Generate optimizer report (best design + histories + polars)
python3 scripts/generate_optimizer_report.py --summary-json results/optimizer_runs/20260222_153621/summary.json --top-n 5

## Live dashboard (local)
python3 scripts/monitor_dashboard.py --port 8000

## Expose dashboard via ngrok (Windows)
ngrok http 8000
