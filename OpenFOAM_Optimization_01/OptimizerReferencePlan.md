1. Project Overview

Automated optimization of a drone airframe using OpenVSP (Geometry/Stability) and OpenFOAM (High-Fidelity CFD).

    Goal: Maximize L/D at 8° and ensure Static Margin is within flyable limits (5-15%).

    Variables: 15 Design Variables (Span, Sweep, Chord, etc.).

    Logic: Python Master Script → OpenVSP Batch → OpenFOAM Sweep → Result Scoring.

2. Directory Structure

    geometry/: Master .vsp3 and .des files.

    templates/drone_template/: Clean OpenFOAM case (gold standard).

    cases/iterations/: Working directory for each optimizer run (iter_001, iter_002...).

    scripts/: Centralized logic (run_sweep.sh, data_analysis.py).

    scripts/vsp_utils/: OpenVSP AngelScripts and metadata parsers.

3. Implementation Phases
Phase A: The Geometry Engine (The "Concierge")

    [x] Task 1: Write scripts/vsp_utils/export_geom.vspscript.

        Load .vsp3 and .des.

        Run CompGeom for a watertight mesh.

        Export baseline.stl for snappyHexMesh.

        Export MassProp.csv for CG and DegenGeom for Aref​.

    [ ] Task 2: Test batch execution in WSL: vsp -batch geometry/baseline.vsp3 -des geometry/baseline.des -script scripts/vsp_utils/export_geom.vspscript

Phase B: The Pipeline Python Utility

    [ ] Task 3: Create a parser to extract CG, Area, and Chord from VSP output files.

    [ ] Task 4: Create a dictionary injector to overwrite system/forceCoeffs and system/snappyHexMeshDict with fresh metadata.

Phase C: Master Optimizer Integration

    [ ] Task 5: Adapt optimizer3.py to:

        Generate a unique iter_XXX folder in cases/iterations/.

        Trigger the Geometry Engine (Phase A).

        Trigger the CFD Sweep (scripts/run_sweep.sh).

        Call the Analysis Script (scripts/data_analysis.py).

        Pass the final score back to the optimization algorithm (Scipy/CMA-ES).

Phase D: Cleanup & Scale

    [ ] Task 6: Add "auto-clean" logic to delete bulky OpenFOAM mesh data after an iteration is scored (keeping only logs and small results).

    [ ] Task 7: Run a 3-iteration test loop to verify stability.

4. Key Physics Constraints

    Design Speed: 25 m/s.

    AoA Sweep: 0, 2, 4, 6, 8, 10 degrees.

    Stability Target: Positive Static Margin (Cm,α​<0).