# Script Data Flow Tracker

This file tracks what each `scripts/*.py` and `scripts/vsp_utils/*.vspscript` file does, what it reads, and what it generates for a specific `.vsp3` geometry.

## Quick Pipeline (Geometry -> OpenFOAM)

1. Run `scripts/vsp_utils/export_geom.vspscript`
2. Run `scripts/vsp_utils/export_frontal_area.vspscript`
3. Run `scripts/compute_openfoam_refs.py`
4. Run `scripts/parse_vsp_outputs.py`
5. Run `scripts/inject_openfoam_dicts.py`
6. (After CFD runs) run `scripts/data_analysis.py`

## Script Inventory

### `scripts/vsp_utils/export_geom.vspscript`
- Purpose: Load baseline geometry + DES, then export mass properties and degen lifting-surface plate CSVs.
- Reads:
  - `geometry/source/baseline.vsp3`
  - `geometry/source/baseline.des`
- Writes:
  - `geometry/outputs/baseline_massprops.csv`
  - `geometry/outputs/degen_<LIFTING_SURFACE_NAME>_plates.csv` (one per lifting surface)
- Produces key values:
  - `Total_CG` (in mm) via `MassProp`
  - Degen plate geometry data per lifting surface
- Consumed by:
  - `scripts/parse_vsp_outputs.py` (massprops CSV)

Notes:
- Despite the filename, this script currently does **not** call `ExportFile(..., EXPORT_STL)`; it does mass/degen exports.

### `scripts/vsp_utils/export_frontal_area.vspscript`
- Purpose: Run VSP `Projection` analysis in X projection direction and export frontal area.
- Reads:
  - `geometry/source/baseline.vsp3`
  - `geometry/source/baseline.des`
- Writes:
  - `geometry/outputs/baseline_frontal_area.csv`
- Produces key values:
  - `Area` (mm^2 in CSV; converted later to m^2)
- Consumed by:
  - `scripts/parse_vsp_outputs.py`

### `scripts/compute_openfoam_refs.py`
- Purpose: Compute OpenFOAM reference quantities from `baseline.des` wing params.
- Reads:
  - `geometry/source/baseline.des`
- Writes:
  - `geometry/outputs/wing_refs.csv`
- Produces key values:
  - `Aref_m2`
  - `bref_m`
  - `lref_m`
- Consumed by:
  - `scripts/parse_vsp_outputs.py`

Implementation detail:
- Uses:
  - `Lwing:XSec_1:Span`
  - `Lwing:XSec_1:Tip_Chord`
  - `Lwing:XSec_1:Taper`
- Uses configured `FUSE_HALF_MM` to compute exposed span.

### `scripts/parse_vsp_outputs.py`
- Purpose: Merge VSP-derived CSVs into one normalized dictionary for downstream use.
- Reads:
  - `geometry/outputs/baseline_massprops.csv`
  - `geometry/outputs/baseline_frontal_area.csv`
  - `geometry/outputs/wing_refs.csv`
- Writes:
  - No file output by default (prints values; returns dict in code)
- Produces key values (all SI units):
  - `cg_x`, `cg_y`, `cg_z` (m)
  - `area_frontal` (m^2)
  - `area_ref` (m^2)
  - `span_ref` (m)
  - `chord_ref` (m)
- Consumed by:
  - `scripts/inject_openfoam_dicts.py`
  - Any orchestration scripts that import `parse_all_vsp_outputs(...)`

### `scripts/inject_openfoam_dicts.py`
- Purpose: Inject parsed VSP reference values into OpenFOAM dictionaries.
- Reads:
  - Parsed dict from `parse_vsp_outputs.py`
  - OpenFOAM files in `<case_dir>/system/`
- Writes:
  - `<case_dir>/system/forceCoeffs`
  - `<case_dir>/system/snappyHexMeshDict`
  - Backup files once (if absent):
    - `forceCoeffs.backup`
    - `snappyHexMeshDict.backup`
- Updates key fields:
  - `CenterOfRotation` <- `(cg_x, cg_y, cg_z)`
  - `Aref` <- `area_ref`
  - `lref` <- `chord_ref`
  - `bref` <- `span_ref` (only if field exists)
  - `locationInMesh` <- `(cg_x, cg_y, cg_z + 0.01)`

### `scripts/data_analysis.py`
- Purpose: Post-process completed AoA runs and generate polar/efficiency outputs.
- Reads:
  - `results_alpha_<a>/postProcessing/forceCoeffs1/0/forceCoeffs.dat` for angles `[0,2,4,6,8,10]`
- Writes:
  - `drone_performance_results.png`
- Produces key values:
  - Per-angle `Cm`, `Cd`, `Cl`, computed `L_D`
  - Static margin estimate from linear fit: `-(dCm/dCl)` as `% MAC`

## File/Artifact Map

- `baseline.vsp3` + `baseline.des`
  - -> `export_geom.vspscript` -> `baseline_massprops.csv` (+ degen CSVs)
  - -> `export_frontal_area.vspscript` -> `baseline_frontal_area.csv`
  - -> `compute_openfoam_refs.py` -> `wing_refs.csv`
- `baseline_massprops.csv` + `baseline_frontal_area.csv` + `wing_refs.csv`
  - -> `parse_vsp_outputs.py` -> normalized VSP/OpenFOAM reference dictionary
- normalized dictionary + `<case_dir>/system/*`
  - -> `inject_openfoam_dicts.py` -> updated `forceCoeffs` and `snappyHexMeshDict`
- CFD outputs (`forceCoeffs.dat` across alpha runs)
  - -> `data_analysis.py` -> plots + summary table + static margin

## Important Consistency Checks

- Units:
  - VSP CSV values are commonly in mm or mm^2.
  - Parser converts to meters and m^2.
- Naming:
  - `export_geom.vspscript` currently exports mass/degen, not STL.
- Paths:
  - Several scripts hard-code `Z:/home/jwhite/JWsim/OpenFOAM_Optimization_01/...`.
  - If repo path changes, update these constants first.
- Case injection assumptions:
  - `forceCoeffs` and `snappyHexMeshDict` must contain regex-matched keys (`Aref`, `lref`, `CenterOfRotation`, `locationInMesh`).

## Recommended Canonical Run Command Sequence

```bash
# 1) Export VSP-derived CSV artifacts
vsp.exe -batch geometry/source/baseline.vsp3 -des geometry/source/baseline.des -script scripts/vsp_utils/export_geom.vspscript
vsp.exe -batch geometry/source/baseline.vsp3 -des geometry/source/baseline.des -script scripts/vsp_utils/export_frontal_area.vspscript
python3 scripts/compute_openfoam_refs.py

# 2) Parse and inject into an OpenFOAM case (example via python import)
python3 scripts/parse_vsp_outputs.py
python3 scripts/inject_openfoam_dicts.py

# 3) After CFD sweeps complete
python3 scripts/data_analysis.py
```
