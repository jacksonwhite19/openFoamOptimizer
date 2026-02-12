# OpenVSP to OpenFOAM Automated Optimization Pipeline
## High-Level Plan & Task Overview

---

## 1. Executive Summary

This document outlines the complete workflow for automating aerodynamic optimization of a fixed-wing drone geometry. The pipeline bridges OpenVSP (parametric geometry) with OpenFOAM (high-fidelity RANS CFD), replacing VSPAERO's panel method with viscous flow simulation to obtain accurate CL, CD, and L/D data across the design space.

**Core Objective**: Generate force coefficients (CL, CD, CM) for arbitrary wing planforms at multiple angles of attack, feeding this data to an optimization algorithm for design iteration.

---

## 2. System Architecture Overview

```
[Optimization Algorithm] 
    ↓ (design variables)
[OpenVSP] → STL Export → Unit Conversion
    ↓
[OpenFOAM Mesh Generation] → Quality Checks
    ↓
[Flow Solver Loop] → α sweep → Convergence Monitoring
    ↓
[Force Extraction] → CL, CD, CM averaging
    ↓
[Results Database] → feedback to optimizer
```

---

## 3. Data Schema Definition

### 3.1 Master Configuration File: `optimization_params.json`

**Purpose**: Single source of truth for all run parameters.

**Required Sections**:

#### Project Metadata
- Project name
- Run identifier/version
- Output directory structure

#### Flow Conditions
- Freestream velocity (u_inf) [m/s]
- Air density (rho) [kg/m³]
- Kinematic viscosity (nu) [m²/s]
- Turbulence intensity (I) [0-1]
- Reynolds number (computed or specified)

#### Geometry Reference Parameters
- VSP3 file path
- Reference area (A_ref) [m²]
- Reference chord (c_ref) [m]
- Reference span (b_ref) [m]
- Target origin coordinates [x, y, z]
- Expected wingspan for scale validation

#### Domain Definition
- X-range: [upstream, downstream] in chord lengths
- Y-range: [±span] in span multiples
- Z-range: [floor, ceiling] in chord lengths
- Recommended: [-5c, 10c] × [±3b] × [±3c]

#### Angle of Attack Sweep
- AOA list: [α₁, α₂, ..., αₙ] in degrees
- Strategy: "rotate_flow" or "rotate_geometry"

#### Mesh Control Parameters
- Surface refinement levels: [min, max]
- Wake refinement level
- Boundary layer: number of layers, first layer thickness
- Cell count targets (min/max)

#### Mesh Quality Thresholds
- Max non-orthogonality (70 typical)
- Max skewness (4 typical)
- Max aspect ratio (100 typical)

#### Solver Control
- Max iterations per AOA
- Residual targets: {p, U, k, omega}
- Convergence window size (iterations for averaging)
- Parallel decomposition: number of processors

#### Output Requirements
- Fields to extract: [CL, CD, CM, L/D, Cp_distribution]
- Averaging window for forces (last N iterations)
- Force coefficient stability thresholds

---

## 4. Phase 0: Human Pre-Requisites (Manual Setup)

**These tasks must be completed before automation begins.**

### 4.0.1 Base Case Template
- [ ] Copy OpenFOAM tutorial: `tutorials/incompressible/simpleFoam/motorBike`
- [ ] Verify tutorial runs successfully on target hardware
- [ ] Document computational resources (cores, RAM, storage)

### 4.0.2 Domain Configuration
- [ ] Edit `system/blockMeshDict`:
  - Set domain bounds from JSON `domain_limits`
  - Ensure cubic/near-cubic cells in vehicle region (aspect ratio ~1)
  - Define grading toward vehicle location
- [ ] Document background mesh resolution strategy

### 4.0.3 Physics Model Selection
- [ ] Set turbulence model: kOmegaSST in `constant/turbulenceProperties`
- [ ] Configure wall functions: nutUSpaldingWallFunction typical
- [ ] Verify incompressible assumption valid (M < 0.3)

### 4.0.4 Software Environment
- [ ] Verify OpenVSP accessible: `vsp` command in PATH
- [ ] Source OpenFOAM environment (version documented)
- [ ] Test parallel execution: `mpirun` functional
- [ ] Install any Python dependencies for automation scripts

### 4.0.5 OpenVSP Export Script Preparation
- [ ] Create `export_stl.vspscript` for headless STL export
- [ ] Define export settings: units, tessellation density
- [ ] Test manual export to verify watertight geometry
- [ ] Document expected STL patch naming convention

### 4.0.6 Validation Data Collection
- [ ] Run baseline geometry in VSPAERO at target α values
- [ ] Record CL, CD for sanity checking OpenFOAM results
- [ ] Document expected performance characteristics

---

## 5. Phase 1: Geometry Processing & Mesh Generation

**Goal**: Transform parametric VSP geometry into a solver-ready computational mesh.

### 5.1 OpenVSP Geometry Export

#### 5.1.1 Headless Export Execution
- [ ] Parse `vsp_file` path from JSON
- [ ] Execute: `vsp -batch <file>.vsp3 -script export_stl.vspscript`
- [ ] Verify STL file created: `constant/triSurface/vehicle.stl`

#### 5.1.2 Geometry Quality Pre-Check
- [ ] Run: `surfaceCheck constant/triSurface/vehicle.stl`
- [ ] Verify output shows:
  - Closed surface (watertight)
  - Number of triangles (logged)
  - Bounding box coordinates
- [ ] Log surface area and characteristic dimensions

### 5.2 Coordinate System Normalization

#### 5.2.1 Scale Verification (GATE 1)
- [ ] Extract STL bounding box from `surfaceCheck` output
- [ ] Compare wingspan (Y-extent) to `b_ref` from JSON
- [ ] Calculate scale error: |STL_span - expected_span| / expected_span
- [ ] **PASS CRITERION**: Error < 1%
- [ ] **FAIL ACTION**: Apply scale transformation or flag unit mismatch

#### 5.2.2 Unit Conversion Strategy
- [ ] Determine if STL is in inches/millimeters/meters
- [ ] If mismatch detected:
  - Document conversion factor
  - Apply: `surfaceTransformPoints -scale "(factor factor factor)" constant/triSurface/vehicle.stl`
  - Re-run verification

#### 5.2.3 Origin Alignment
- [ ] Calculate STL geometric center
- [ ] Compare to `target_origin` from JSON
- [ ] If offset > 0.01m:
  - Calculate translation vector
  - Apply: `surfaceTransformPoints -translate "(dx dy dz)" constant/triSurface/vehicle.stl`
- [ ] Verify vehicle now centered in domain

### 5.3 Background Mesh Generation

#### 5.3.1 BlockMesh Execution
- [ ] Run: `blockMesh`
- [ ] Verify output: background mesh created
- [ ] Log cell count (should be ~1-10k cells)

#### 5.3.2 Surface Feature Extraction
- [ ] Run: `surfaceFeatureExtract`
- [ ] Verify: `constant/triSurface/vehicle.eMesh` created
- [ ] This defines sharp edges for mesh snapping

### 5.4 SnappyHexMesh Configuration

#### 5.4.1 Refinement Region Definition
- [ ] Define wake region box:
  - Extends downstream 5-10 chord lengths
  - Width: ±1 span
  - Height: ±0.5 span
- [ ] Set refinement levels in `system/snappyHexMeshDict`:
  - Surface: levels from JSON `mesh_params.surface_refinement`
  - Wake: level from JSON `mesh_params.wake_refinement`
  - Background: coarse

#### 5.4.2 Boundary Layer Specification
- [ ] Configure layer addition:
  - Number of layers from JSON
  - First layer thickness (y+ target ~1 for wall-resolved)
  - Expansion ratio (1.2 typical)

#### 5.4.3 Snapping and Layer Addition
- [ ] Run: `snappyHexMesh -overwrite`
- [ ] Monitor output for:
  - Successful snapping percentage (>90%)
  - Layer coverage percentage (>80%)
  - Final cell count (log for performance tracking)

### 5.5 Mesh Quality Validation (GATE 2)

#### 5.5.1 CheckMesh Execution
- [ ] Run: `checkMesh`
- [ ] Parse output for quality metrics:
  - Non-orthogonality: max and average
  - Skewness: max value
  - Aspect ratio: max value

#### 5.5.2 Quality Gate Criteria
- [ ] **PASS CRITERION**: "Mesh OK" message present
- [ ] **PASS CRITERION**: Max non-orthogonality < threshold (JSON)
- [ ] **PASS CRITERION**: Max skewness < threshold (JSON)
- [ ] **FAIL ACTION**: Adjust refinement, retry snappy

#### 5.5.3 Mesh Statistics Logging
- [ ] Extract and log:
  - Total cell count
  - Boundary layer cells count
  - Min/max cell volume
  - Memory estimate for solver

---

## 6. Phase 2: Flow Physics Setup

**Goal**: Configure turbulence model, boundary conditions, and initial fields.

### 6.1 Turbulence Initialization

#### 6.1.1 Turbulent Kinetic Energy (k)
- [ ] Calculate from JSON turbulence intensity:
  - k = 1.5 × (u_inf × I)²
- [ ] Create/modify `0/k`:
  - internalField: uniform k
  - inlet: fixedValue k
  - outlet: zeroGradient
  - walls: kqRWallFunction

#### 6.1.2 Specific Dissipation Rate (ω)
- [ ] Calculate from mixing length approximation:
  - L = 0.09 × c_ref
  - ε = k^1.5 / (0.09 × c_ref)
  - ω = ε / (0.09 × k)
- [ ] Create/modify `0/omega`:
  - internalField: uniform ω
  - inlet: fixedValue ω
  - outlet: zeroGradient
  - walls: omegaWallFunction

#### 6.1.3 Turbulent Viscosity (nut)
- [ ] Set initial estimate: nut = k/ω
- [ ] Create `0/nut`:
  - internalField: uniform nut
  - inlet: calculated
  - walls: nutUSpaldingWallFunction

### 6.2 Angle of Attack Implementation

#### 6.2.1 Strategy Selection
**Option A: Rotate Flow Direction**
- [ ] For each α in JSON `aoa_range`:
  - Calculate velocity components:
    - Ux = u_inf × cos(α)
    - Uy = 0
    - Uz = u_inf × sin(α)
  - Update `0/U` inlet boundary
- [ ] Advantage: Single mesh for all α
- [ ] **RECOMMENDED for optimization**

**Option B: Rotate Geometry**
- [ ] For each α:
  - Rotate STL about Y-axis
  - Re-mesh with snappyHexMesh
- [ ] Disadvantage: Mesh generation overhead
- [ ] Use only if flow rotation causes convergence issues

#### 6.2.2 Reference Frame Definition
- [ ] Document coordinate system:
  - X: streamwise (flow direction at α=0)
  - Y: spanwise
  - Z: vertical (lift direction)
- [ ] Verify with right-hand rule

### 6.3 Boundary Conditions Specification

#### 6.3.1 Velocity (U)
- [ ] Inlet: fixedValue with velocity vector from α
- [ ] Outlet: zeroGradient
- [ ] Walls (vehicle): noSlip
- [ ] Far-field boundaries: slip or freestream

#### 6.3.2 Pressure (p)
- [ ] Inlet: zeroGradient
- [ ] Outlet: fixedValue uniform 0
- [ ] Walls: zeroGradient
- [ ] Reference pressure: 0 Pa (gauge)

#### 6.3.3 Turbulence Fields
- [ ] Apply calculated k and ω to boundaries
- [ ] Wall functions for k, ω, nut

### 6.4 Force Coefficient Function Object

#### 6.4.1 Configuration File Creation
- [ ] Create/edit `system/forceCoeffs`:
  - Type: forceCoeffs
  - Patches: (vehicle) - **must match STL patch name**
  - Reference values from JSON:
    - rhoInf
    - magUInf
    - lRef (c_ref)
    - Aref (A_ref)
  - Center of rotation: target_origin
  - Axis definitions:
    - liftDir: (0 0 1)
    - dragDir: (1 0 0) at α=0
    - pitchAxis: (0 1 0)

#### 6.4.2 Coordinate System Verification
- [ ] **CRITICAL**: Verify force directions align with:
  - Positive lift = upward (+Z)
  - Positive drag = downstream (+X)
- [ ] Test with known geometry to validate signs

#### 6.4.3 Output Configuration
- [ ] Set writeControl: timeStep
- [ ] Set writeInterval: 10 (balance I/O vs. resolution)
- [ ] Output location: `postProcessing/forceCoeffs/0/`

---

## 7. Phase 3: Solver Execution & Convergence Monitoring

**Goal**: Run SimpleFoam to steady-state convergence with robust monitoring.

### 7.1 Parallel Decomposition (if applicable)

#### 7.1.1 Domain Decomposition
- [ ] Create `system/decomposeParDict`:
  - numberOfSubdomains from JSON
  - method: scotch (load balanced)
- [ ] Run: `decomposePar`
- [ ] Verify processor directories created

### 7.2 Solver Execution

#### 7.2.1 Serial Run
- [ ] Command: `simpleFoam > log.simpleFoam 2>&1`
- [ ] Use for small meshes (<100k cells)

#### 7.2.2 Parallel Run
- [ ] Command: `mpirun -np <N> simpleFoam -parallel > log.simpleFoam 2>&1`
- [ ] N from JSON `solver_params.n_processors`

### 7.3 Real-Time Convergence Monitoring

#### 7.3.1 Residual Tracking (GATE 3)
- [ ] Monitor `log.simpleFoam` for residuals:
  - Variables: p, Ux, Uy, Uz, k, omega
  - Target final residuals from JSON
- [ ] **Early Check at Iteration 100**:
  - Verify residuals decreasing (not flat or increasing)
  - If diverging: STOP, flag for review

#### 7.3.2 Residual Convergence Criteria
- [ ] **PASS CRITERION**: All residuals below targets:
  - p < 1e-4
  - U < 1e-5
  - k, omega < 1e-4
- [ ] Evaluate over last 100 iterations (moving average)

#### 7.3.3 Force Coefficient Stability
- [ ] Monitor `postProcessing/forceCoeffs/0/forceCoeffs.dat`
- [ ] Track CL and CD real-time
- [ ] **PASS CRITERION**: Over last 50 iterations:
  - std(CL) < 0.001
  - std(CD) < 0.0001
- [ ] This indicates quasi-steady state

#### 7.3.4 Iteration Limit
- [ ] **TIMEOUT**: If iterations exceed JSON max_iterations:
  - Flag as non-converged
  - Extract best available data
  - Log for optimizer (penalize design)

### 7.4 Solver Stability Diagnostics

#### 7.4.1 Divergence Detection
- [ ] If any residual > 1e3: solver diverging
- [ ] Possible causes:
  - Mesh quality poor
  - Timestep/relaxation too aggressive
  - Boundary conditions incorrect

#### 7.4.2 Stall/Oscillation Detection
- [ ] If residuals oscillate without decreasing:
  - Likely flow unsteadiness (vortex shedding at high α)
  - May need transient solver (pimpleFoam)
  - Document and flag

---

## 8. Phase 4: Force Extraction & Data Processing

**Goal**: Extract converged force coefficients and prepare for optimizer.

### 8.1 Force Coefficient Data Parsing

#### 8.1.1 File Location
- [ ] Primary data: `postProcessing/forceCoeffs/0/forceCoeffs.dat`
- [ ] Columns: Time, Cm, Cd, Cl, Cl(f), Cl(r)

#### 8.1.2 Convergence Window Averaging
- [ ] Extract last N iterations (N from JSON)
- [ ] Calculate:
  - CL_mean = mean(CL[-N:])
  - CD_mean = mean(CD[-N:])
  - CM_mean = mean(CM[-N:])
  - CL_std, CD_std for quality check

#### 8.1.3 Data Sanity Checks (GATE 4)
- [ ] **Physical Plausibility**:
  - CL > 0 for positive α (typically)
  - CD > 0 always
  - 0.01 < CD < 0.5 (rough range for drones)
- [ ] **Statistical Stability**:
  - CL_std / CL_mean < 0.1 (10% variation acceptable)
  - CD_std / CD_mean < 0.05
- [ ] **Comparison to Baseline**:
  - If VSPAERO data available, CL should be within 20%
  - CD will be higher (viscous effects)

### 8.2 Derived Quantities

#### 8.2.1 Lift-to-Drag Ratio
- [ ] Calculate: L/D = CL / CD
- [ ] Log for optimizer (primary performance metric)

#### 8.2.2 Dimensional Forces
- [ ] L = CL × 0.5 × ρ × V² × A_ref
- [ ] D = CD × 0.5 × ρ × V² × A_ref
- [ ] Useful for power/range calculations

### 8.3 Results Database Output

#### 8.3.1 Create `results.json` for Current Run
```json
{
  "geometry_id": "<hash or design_vector>",
  "alpha_deg": <current α>,
  "converged": true/false,
  "iterations": <N>,
  "force_coefficients": {
    "CL": <value>,
    "CL_std": <value>,
    "CD": <value>,
    "CD_std": <value>,
    "CM": <value>,
    "L_D": <value>
  },
  "mesh_stats": {
    "cells": <N>,
    "wall_clock_seconds": <T>
  },
  "quality_flags": {
    "mesh_ok": true,
    "residuals_converged": true,
    "forces_stable": true
  }
}
```

#### 8.3.2 Append to Master Database
- [ ] Aggregate results across α sweep
- [ ] Format for optimizer consumption
- [ ] Include failure flags for penalty functions

---

## 9. Phase 5: Multi-Alpha Sweep Orchestration

**Goal**: Automate iteration over angle of attack range.

### 9.1 Alpha Loop Structure

#### 9.1.1 For Each α in JSON `aoa_range`:
- [ ] Update flow direction in `0/U` (if using flow rotation)
- [ ] OR re-export/re-mesh geometry (if using geometry rotation)
- [ ] Run solver to convergence
- [ ] Extract forces
- [ ] Append to results database

#### 9.1.2 Incremental Initialization
- [ ] For α_n, use α_{n-1} solution as initial condition
- [ ] Copy field data: `cp -r <prev_time>/* 0/`
- [ ] Accelerates convergence for nearby α values

### 9.2 Polar Curve Construction

#### 9.2.1 Data Aggregation
- [ ] Compile CL(α), CD(α), CM(α)
- [ ] Identify:
  - CL_max (stall angle)
  - (L/D)_max (best glide)
  - α for target CL (cruise condition)

#### 9.2.2 Curve Fitting (Optional)
- [ ] Fit polynomial to CL(α) for interpolation
- [ ] Fit drag polar: CD = CD0 + k×CL²
- [ ] Extract induced drag factor k

---

## 10. Failure Recovery & Error Handling

**Goal**: Define specific recovery actions for each failure mode.

### 10.1 Error Code System

#### ERROR 1: STL_SCALE_MISMATCH
- **Detection**: Scale check >1% error
- **Diagnosis**: Check VSP units setting (inches vs. meters)
- **Action**: Apply `surfaceTransformPoints -scale`
- **Prevention**: Document unit convention in VSP export script

#### ERROR 2: MESH_NOT_OK
- **Detection**: checkMesh reports fatal errors
- **Diagnosis**: Non-orthogonality, skewness exceeded
- **Action**: 
  - Reduce refinement level by 1
  - Increase feature angle tolerance
  - Simplify geometry (remove small features)
- **Prevention**: Conservative initial refinement

#### ERROR 3: SOLVER_DIVERGED
- **Detection**: Residuals > 1e3 or NaN
- **Diagnosis**:
  - Check mesh quality (re-run checkMesh)
  - Inspect initial conditions (k, omega physical?)
  - Review boundary conditions
- **Action**:
  - Reduce relaxation factors in fvSolution
  - Lower CFL-equivalent (reduce solver aggressiveness)
  - Re-initialize with more conservative ICs
- **Prevention**: Validate BCs against tutorial cases

#### ERROR 4: FORCE_COEFF_NAN
- **Detection**: NaN in forceCoeffs.dat
- **Diagnosis**: 
  - Patch name mismatch (forceCoeffs looking at wrong surface)
  - Pressure field corruption
- **Action**:
  - Verify patch name: `foamListPatches`
  - Check that vehicle patch exists
  - Restart solve from earlier time
- **Prevention**: Test forceCoeffs on motorBike tutorial first

#### ERROR 5: CONVERGENCE_TIMEOUT
- **Detection**: Iterations > max without meeting criteria
- **Diagnosis**:
  - Flow may be inherently unsteady (high α, separation)
  - Mesh too coarse to resolve flow features
  - Relaxation factors too conservative (slow convergence)
- **Action**:
  - If residuals still decreasing: extend max iterations
  - If oscillating: switch to transient solver (pimpleFoam)
  - If stalled: adjust relaxation factors upward
- **Prevention**: Set realistic max iterations based on mesh size

#### ERROR 6: NEGATIVE_DRAG
- **Detection**: CD < 0
- **Diagnosis**: dragDir axis definition incorrect
- **Action**:
  - Verify coordinate system in forceCoeffs
  - Check if flow direction aligns with dragDir
  - May need to flip dragDir sign
- **Prevention**: Test with zero-AoA symmetric airfoil first

#### ERROR 7: LAYER_ADDITION_FAILED
- **Detection**: snappyHexMesh reports low layer coverage
- **Diagnosis**:
  - First layer too thin (y+ < 0.1)
  - Concave surface regions
- **Action**:
  - Increase first layer thickness
  - Reduce number of layers
  - Adjust expansion ratio
- **Prevention**: Start with wall functions (y+ ~ 30-100)

### 10.2 Automated Recovery Strategies

#### 10.2.1 Retry Logic
- [ ] For transient errors (disk I/O, memory):
  - Retry up to 3 times
  - Exponential backoff
- [ ] For deterministic errors:
  - Apply fix, retry once
  - If fails again: escalate to human

#### 10.2.2 Graceful Degradation
- [ ] If high-α cases fail (separated flow):
  - Flag as unconverged
  - Assign penalty value to optimizer
  - Continue with remaining α values
- [ ] Document partial results

---

## 11. Validation & Testing Strategy

**Goal**: Prove pipeline correctness before production runs.

### 11.1 Unit Tests (Individual Phases)

#### Test 1: Geometry Export & Scale
- [ ] **Input**: Known VSP file with documented wingspan
- [ ] **Action**: Export STL, run scale check
- [ ] **Pass**: Wingspan matches within 0.1%

#### Test 2: Mesh Generation Repeatability
- [ ] **Input**: Fixed STL geometry
- [ ] **Action**: Run meshing twice with same parameters
- [ ] **Pass**: Cell count identical, checkMesh results identical

#### Test 3: Zero-AoA Symmetry
- [ ] **Input**: Symmetric airfoil at α=0
- [ ] **Action**: Run solver
- [ ] **Pass**: CL ≈ 0 (within ±0.001), forces symmetric

#### Test 4: Force Direction Verification
- [ ] **Input**: Flat plate at α=10°
- [ ] **Action**: Extract forces
- [ ] **Pass**: CL > 0, CD > 0, signs correct

### 11.2 Integration Tests (End-to-End)

#### Test 5: Single-Alpha Complete Pipeline
- [ ] **Input**: Baseline geometry, α=5°
- [ ] **Action**: Run all phases
- [ ] **Pass**: 
  - results.json created
  - CL, CD within expected range
  - Converged flag = true

#### Test 6: Alpha Sweep
- [ ] **Input**: α = [0, 2, 4, 6] degrees
- [ ] **Action**: Full pipeline
- [ ] **Pass**:
  - CL increases monotonically (pre-stall)
  - CD increases with α²
  - All runs converge

### 11.3 Validation Against Known Data

#### Test 7: NACA Airfoil Comparison
- [ ] **Input**: NACA 2412 at Re=500k, α=5°
- [ ] **Action**: Run pipeline
- [ ] **Pass**: CL within 5% of published data

#### Test 8: VSPAERO Cross-Check
- [ ] **Input**: Baseline drone geometry
- [ ] **Action**: Compare OpenFOAM vs. VSPAERO at α=0,5,10°
- [ ] **Expected**: 
  - CL similar (within 10%)
  - CD higher in OpenFOAM (viscous)
  - Trends agree

---

## 12. Performance Optimization & Scalability

**Goal**: Minimize wall-clock time for optimization iterations.

### 12.1 Mesh Size Tuning

#### 12.1.1 Sensitivity Study
- [ ] Run same geometry with:
  - Coarse: ~100k cells
  - Medium: ~500k cells
  - Fine: ~2M cells
- [ ] Compare CL, CD convergence
- [ ] Select minimum mesh for <2% error

#### 12.1.2 Adaptive Refinement (Future)
- [ ] Start with coarse mesh
- [ ] Identify high-gradient regions
- [ ] Refine and re-solve
- [ ] Iterate until converged

### 12.2 Parallel Scaling

#### 12.2.1 Decomposition Strategy
- [ ] Test processor counts: [4, 8, 16, 32]
- [ ] Measure speedup vs. serial
- [ ] Identify optimal N (diminishing returns)

#### 12.2.2 Load Balancing
- [ ] Use scotch decomposition (better than simple)
- [ ] Monitor processor utilization
- [ ] Aim for >80% parallel efficiency

### 12.3 Solver Settings Optimization

#### 12.3.1 Relaxation Factors
- [ ] Start conservative (0.3 for p, 0.7 for U)
- [ ] Increase if stable (up to 0.9)
- [ ] Balance convergence speed vs. stability

#### 12.3.2 Linear Solver Selection
- [ ] Test PCG vs. GAMG for pressure
- [ ] Smooth Solver vs. PCG for velocity
- [ ] Document fastest combination

### 12.4 I/O Reduction

#### 12.4.1 Field Writing
- [ ] Disable auto-write of all fields during solve
- [ ] Write only final timestep
- [ ] Keep only forceCoeffs time history

#### 12.4.2 Disk Space Management
- [ ] After each α case:
  - Archive critical data (forceCoeffs, mesh)
  - Delete intermediate timesteps: `foamListTimes -rm`
  - Compress if storage limited

---

## 13. Optimizer Integration

**Goal**: Interface CFD pipeline with optimization algorithm.

### 13.1 Design Variables Encoding

#### 13.1.1 VSP Parameterization
- [ ] Define design vector components:
  - Wing planform: span, taper, sweep
  - Airfoil: thickness, camber
  - Twist distribution
- [ ] Map to VSP API calls
- [ ] Document bounds and constraints

#### 13.1.2 Geometry Update Workflow
- [ ] Optimizer proposes design vector
- [ ] Update VSP file programmatically
- [ ] Trigger pipeline execution
- [ ] Return objective function value

### 13.2 Objective Function Definition

#### 13.2.1 Primary Metrics
- [ ] Maximize: L/D at cruise condition
- [ ] OR Minimize: CD at target CL
- [ ] OR Multi-objective: [max L/D, min mass]

#### 13.2.2 Constraint Handling
- [ ] Enforce:
  - CL_max > 1.2 (stall margin)
  - Structural feasibility (aspect ratio limits)
  - Manufacturing constraints
- [ ] Penalty method for violations

#### 13.2.3 Failure Penalty
- [ ] If CFD fails to converge:
  - Assign large penalty value
  - Optimizer steers away from region
  - Log failure for post-analysis

### 13.3 Optimization Algorithm Selection

#### 13.3.1 Gradient-Free Methods (Recommended Initially)
- [ ] Particle Swarm Optimization (PSO)
- [ ] Genetic Algorithm (GA)
- [ ] Bayesian Optimization (BO)
- [ ] Pro: Robust to noise, parallelizable
- [ ] Con: Requires many evaluations (50-500)

#### 13.3.2 Gradient-Based Methods (Advanced)
- [ ] Adjoint sensitivity analysis
- [ ] Requires: adjointShapeOptimizationFoam
- [ ] Pro: Fast convergence (10-50 iterations)
- [ ] Con: Complex setup, local optima

---

## 14. Documentation & Logging

**Goal**: Traceability for debugging and reproducibility.

### 14.1 Run Metadata Logging

#### For Each CFD Run, Log:
- [ ] Timestamp (start, end)
- [ ] Design vector values
- [ ] Mesh statistics (cells, quality)
- [ ] Solver iterations to convergence
- [ ] Wall-clock time
- [ ] Force coefficients
- [ ] Convergence status
- [ ] Error codes (if failed)

### 14.2 Directory Structure

```
project_root/
├── optimization_params.json
├── cases/
│   ├── design_0001/
│   │   ├── geometry.vsp3
│   │   ├── constant/
│   │   ├── system/
│   │   ├── 0/
│   │   ├── postProcessing/
│   │   ├── log.simpleFoam
│   │   └── results.json
│   ├── design_0002/
│   └── ...
├── database/
│   └── optimization_history.csv
└── scripts/
    ├── run_pipeline.py
    └── post_process.py
```

### 14.3 Visualization Outputs

#### 14.3.1 Per-Design Plots
- [ ] Residual history (convergence plot)
- [ ] Force coefficient time history
- [ ] Cp distribution on surface

#### 14.3.2 Optimization Progress
- [ ] Objective function vs. iteration
- [ ] Design variable evolution
- [ ] Pareto front (if multi-objective)

---

## 15. Workflow Automation Checklist

**High-level tasks for scripting the pipeline.**

### 15.1 Pre-Flight Checks
- [ ] Verify JSON schema valid
- [ ] Check VSP file exists
- [ ] Confirm OpenFOAM environment sourced
- [ ] Test write permissions on output directory

### 15.2 Phase Execution Sequence
- [ ] Parse JSON into runtime variables
- [ ] Export STL from VSP
- [ ] Run scale verification gate
- [ ] Generate background mesh
- [ ] Run snappyHexMesh
- [ ] Run mesh quality gate
- [ ] Initialize turbulence fields
- [ ] Loop over α:
  - Update boundary conditions
  - Decompose domain (if parallel)
  - Run simpleFoam
  - Monitor convergence
  - Extract forces
  - Reconstruct (if parallel)
- [ ] Aggregate results
- [ ] Write optimizer feedback file
- [ ] Clean up temporary files

### 15.3 Error Handling Hooks
- [ ] Try-catch around each phase
- [ ] Log errors to file
- [ ] Execute recovery action if defined
- [ ] Escalate to human if unrecoverable
- [ ] Continue with next design (don't abort entire batch)

---

## 16. Open Questions & Future Enhancements

### 16.1 Unsteady Flows
- [ ] **Question**: At what α does flow become unsteady?
- [ ] **Action**: Monitor force oscillations; switch to pimpleFoam if needed
- [ ] **Enhancement**: Time-averaged forces from LES/DES

### 16.2 Compressibility Effects
- [ ] **Question**: Is M < 0.3 valid assumption?
- [ ] **Action**: Calculate local Mach number from OpenFOAM
- [ ] **Enhancement**: Switch to rhoPimpleFoam if M > 0.3

### 16.3 Ground Effect
- [ ] **Question**: Does drone operate near ground?
- [ ] **Action**: Add ground plane to domain
- [ ] **Enhancement**: Sweep ground clearance parameter

### 16.4 Propeller Interactions
- [ ] **Question**: Does propwash affect wing?
- [ ] **Action**: Model propeller as actuator disk
- [ ] **Enhancement**: Couple with propeller performance maps

### 16.5 Aeroelastic Effects
- [ ] **Question**: Is wing stiff or flexible?
- [ ] **Action**: If flexible, couple CFD with structural solver
- [ ] **Enhancement**: FSI optimization for flutter margin

---

## 17. Success Criteria for Pipeline Validation

**Before deploying to full optimization, confirm:**

- [ ] ✓ 10 consecutive geometries run without crashes
- [ ] ✓ Force coefficients match VSPAERO within documented tolerances
- [ ] ✓ Mesh generation succeeds >95% of the time
- [ ] ✓ Solver convergence achieved >90% of the time
- [ ] ✓ Wall-clock time per design < budget (e.g., 2 hours)
- [ ] ✓ Results database accumulates correctly
- [ ] ✓ Optimizer successfully iterates (objective improves)

---

## 18. Key Milestones & Timeline Estimate

| Milestone | Description | Est. Duration |
|-----------|-------------|---------------|
| M1 | Human setup complete (Phase 0) | 1 week |
| M2 | Single-geometry, single-α runs working | 1 week |
| M3 | Alpha sweep automation functional | 3 days |
| M4 | All validation tests passing | 1 week |
| M5 | Optimizer integration complete | 1 week |
| M6 | First optimization run (10-20 designs) | 2-3 days runtime |
| M7 | Pipeline refinement based on results | Ongoing |

**Total estimated setup: 4-5 weeks of development + testing**

---

## 19. Critical Path Items (Blockers)

**These must be resolved before pipeline can run:**

1. **OpenVSP export script** - Must produce watertight STL reliably
2. **Unit conversion** - Inches to meters or scale validation
3. **Patch naming** - forceCoeffs must reference correct geometry patch
4. **Coordinate system** - Lift/drag directions must be correct
5. **Convergence criteria** - Define quantitative thresholds
6. **Parallel decomposition** - Must work on target hardware
7. **JSON schema** - All tools must parse same parameter file

---

## 20. Stakeholder Review Points

**Decision points requiring human input:**

- [ ] Approve final JSON schema structure
- [ ] Select target Reynolds number and flight conditions
- [ ] Choose optimization algorithm (gradient-free vs. adjoint)
- [ ] Define objective function and constraints
- [ ] Validate first CFD results against VSPAERO
- [ ] Review mesh resolution vs. runtime tradeoff
- [ ] Approve pipeline for production runs

---

## 21. Appendix: Tools & Commands Reference

### A. Essential OpenFOAM Commands
```bash
# Mesh generation
blockMesh
surfaceFeatureExtract
snappyHexMesh -overwrite
checkMesh

# Parallel
decomposePar
mpirun -np 8 simpleFoam -parallel
reconstructPar

# Utilities
surfaceCheck <file.stl>
surfaceTransformPoints -translate "(...)"
foamListPatches
foamListTimes -rm

# Post-processing
foamCalc components U  # Extract velocity components
sample  # Extract line/plane data
```

### B. Python Libraries for Automation
- `json` - Parse optimization_params.json
- `subprocess` - Execute shell commands
- `numpy` - Force coefficient averaging
- `pandas` - Results database management
- `matplotlib` - Convergence plotting

### C. VSP Command-Line Interface
```bash
# Headless mode
vsp -batch <file>.vsp3 -script <script>.vspscript

# Export STL
# (in .vspscript): ExportFile("output.stl", SET_ALL, EXPORT_STL);
```

---

## 22. Final Notes

This plan represents a **high-fidelity CFD optimization pipeline** replacing panel methods with viscous flow simulation. The complexity is justified for:

- Complex 3D planforms where panel methods lose accuracy
- Viscous drag prediction (critical for endurance optimization)
- High-α performance (stall characteristics)
- Detailed flow field analysis (separation, wake)

**Not justified for**:
- Preliminary design (use VSPAERO or empirical methods)
- Simple 2D airfoil studies (XFOIL sufficient)
- Real-time control applications (too slow)

The pipeline should be **validated incrementally** - prove each phase works before chaining them together. Automation should be **robust and logged** - failures will happen, make them debuggable.

**Success means**: The optimizer can reliably explore the design space with accurate force predictions, converging to a superior drone configuration in reasonable time (days, not weeks).