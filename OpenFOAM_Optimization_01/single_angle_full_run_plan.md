# Single Angle Pipeline - Bite-Sized Execution Plan

## Goal
Build and validate one full end-to-end run for a single angle of attack:
- export geometry/reference data from VSP
- create and mesh OpenFOAM case
- run CFD at one angle
- extract final coefficients

Target case: `cases/test_runs/alpha_8`

Last updated: `2026-02-17`

---

## Status Legend
- `[ ]` Not started
- `[~]` In progress
- `[x]` Complete
- `[!]` Blocked

---

## Milestone Definition (Done =)
- `[ ]` Mesh passes `checkMesh` (Mesh OK)
- `[x]` Solver runs without fatal error
- `[x]` Force coefficients file exists and has valid final row
- `[x]` Final run summary captured in `results.json`
- `[x]` Session log updated in `SESSION_PROGRESS_LOG.md`

---

## Current Progress Snapshot
- `[x]` Phase 1 complete (VSP exports + refs computed + parsed)
- `[x]` Phase 2 complete (case present, STL placed, dictionary injection complete)
- `[x]` Phase 3 complete (AoA fields/directions updated for alpha=8)
- `[~]` Phase 4 complete with warning (mesh built; checkMesh skewness gate failed)
- `[x]` Phase 5 complete (single-angle simpleFoam run finished)
- `[x]` Phase 6 complete (coefficients extracted and results.json written)

---

## Phase 0 - Preflight (Small Tasks)

### 0.1 Confirm required inputs exist
- `[x]` `geometry/source/baseline.vsp3`
- `[x]` `geometry/source/baseline.des`
- `[x]` `templates/drone_template/0`
- `[x]` `templates/drone_template/constant`
- `[x]` `templates/drone_template/system`

Evidence:
- command output from `ls`/`Get-ChildItem`

### 0.2 Confirm VSP and OpenFOAM commands are available
- `[~]` `vsp.exe` callable (available on Windows host; not in WSL PATH)
- `[x]` `blockMesh` callable
- `[x]` `snappyHexMesh` callable
- `[x]` `checkMesh` callable
- `[x]` `simpleFoam` callable

Evidence:
- `--help` or version output

---

## Phase 1 - VSP Export + Reference Extraction

### 1.1 Run mass/degen export script
- `[x]` Run `scripts/vsp_utils/export_geom.vspscript`
- `[x]` Verify `geometry/outputs/baseline_massprops.csv` exists
- `[x]` Verify at least one `geometry/outputs/degen_*_plates.csv` exists

### 1.2 Run frontal area export script
- `[x]` Run `scripts/vsp_utils/export_frontal_area.vspscript`
- `[x]` Verify `geometry/outputs/baseline_frontal_area.csv` exists

### 1.3 Compute OpenFOAM refs from DES
- `[x]` Run `python3 scripts/compute_openfoam_refs.py`
- `[x]` Verify `geometry/outputs/wing_refs.csv` exists

### 1.4 Parse and sanity check values
- `[x]` Run `python3 scripts/parse_vsp_outputs.py`
- `[x]` Confirm CG, area_ref, span_ref, chord_ref are positive/reasonable

Exit criteria:
- all three CSV artifacts exist and parse cleanly

---

## Phase 2 - Case Creation + Dictionary Injection

### 2.1 Create a fresh test case
- `[x]` Create `cases/test_runs/alpha_8` from `templates/drone_template`
- `[x]` Confirm copied folders `0/ constant/ system/`

### 2.2 Ensure STL is available to case
- `[x]` Verify STL export path and filename
- `[x]` Copy STL into `cases/test_runs/alpha_8/constant/triSurface/`
- `[x]` Confirm STL size > 0

Note:
- If STL is not currently exported by VSP scripts, mark blocked and add explicit STL export task.

### 2.3 Inject reference values into OpenFOAM dictionaries
- `[x]` Run injection path using `parse_vsp_outputs.py` + `inject_openfoam_dicts.py`
- `[x]` Verify in `system/forceCoeffs`:
  - `CenterOfRotation`
  - `Aref`
  - `lref`
  - `bref` (if present)
- `[x]` Verify in `system/snappyHexMeshDict`:
  - `locationInMesh`

Exit criteria:
- case exists and dictionaries contain injected values

---

## Phase 3 - Single-Angle Setup (alpha = 8 deg)

### 3.1 Set velocity components in `0/U`
- `[x]` Compute `Ux = V*cos(alpha)`, `Uz = V*sin(alpha)`
- `[x]` Update `internalField`
- `[x]` Update inlet boundary `value`

### 3.2 Set lift/drag direction consistency
- `[x]` Verify `dragDir` and `liftDir` are correct for chosen AoA strategy
- `[x]` Confirm force sign convention is documented

Exit criteria:
- `0/U` and `system/forceCoeffs` are consistent with alpha=8 deg

---

## Phase 4 - Mesh Build + Quality Gate

### 4.1 Build base mesh
- `[x]` Run `blockMesh`
- `[x]` Confirm `constant/polyMesh` exists

### 4.2 Extract surface features
- `[x]` Run feature extraction utility used by case (`surfaceFeatures` or `surfaceFeatureExtract`)
- `[x]` Confirm `.eMesh` output exists

### 4.3 Run snappy
- `[x]` Run `snappyHexMesh -overwrite`
- `[x]` Save log (`log.snappyHexMesh`)

### 4.4 Mesh gate
- `[x]` Run `checkMesh`
- `[ ]` Confirm `Mesh OK`
- `[x]` Capture max non-orthogonality and skewness

Exit criteria:
- mesh metrics captured; gate currently fails on skewness (`maxSkewness=5.46194`, `166` highly skew faces)

---

## Phase 5 - Solver Run + Convergence Gate

### 5.1 Smoke test
- `[~]` Short run (e.g., small endTime/iterations)
- `[x]` Confirm solver starts and no immediate fatal errors

### 5.2 Full run
- `[x]` Restore full run controls
- `[x]` Run `simpleFoam` and log to `log.simpleFoam`

### 5.3 Convergence checks
- `[x]` Residuals trend downward
- `[x]` No divergence signatures (NaN / huge residual blow-up)
- `[x]` force coefficients become stable near end window

Exit criteria:
- solver finishes with usable, stable result window

---

## Phase 6 - Result Extraction + Run Record

### 6.1 Locate final force coefficients
- `[x]` Find latest forceCoeffs output directory
- `[x]` Parse last row from coefficients file

### 6.2 Compute summary metrics
- `[x]` Extract `CL`, `CD`, `CM`
- `[x]` Compute `L/D`

### 6.3 Write run summary artifact
- `[x]` Create `cases/test_runs/alpha_8/results.json` with:
  - `alpha_deg`
  - `converged`
  - `iterations`
  - `CL`, `CD`, `CM`, `L_D`
  - mesh quality summary
  - key log file paths

### 6.4 Update tracking docs
- `[x]` Update status in this file
- `[x]` Add session entry to `SESSION_PROGRESS_LOG.md`

Exit criteria:
- one reproducible single-angle result with recorded metrics and evidence

---

## Blockers to Resolve Early
- `[ ]` STL export ownership is explicit and working (script name matches behavior)
- `[x]` Hard-coded absolute paths are handled for this environment (`parse_vsp_outputs.py` and `inject_openfoam_dicts.py` now use relative defaults/CLI args)
- `[ ]` forceCoeffs file naming (`coefficient.dat` vs `forceCoeffs.dat`) confirmed in this case

---

## Immediate Next 5 Tasks
1. `[x]` Verify VSP/OpenFOAM commands available.
2. `[x]` Generate/verify three reference CSV outputs.
3. `[x]` Confirm STL export path + copy STL into case.
4. `[x]` Create fresh `alpha_8` case and inject refs.
5. `[x]` Set AoA in `0/U` and verify `dragDir/liftDir` before meshing.

---

## Notes
- Keep template pristine; never run solver in `templates/drone_template`.
- Keep logs for each major command.
- Do not start sweep/optimizer work until this single-angle milestone is complete.
