"""
Single Angle CFD Pipeline
Runs complete workflow: VSP geometry → OpenFOAM setup → Mesh → Solve → Extract results

Usage:
    python run_single_angle.py --angle 8.0 --case-name test_alpha8
"""

import argparse
import subprocess
import shutil
from pathlib import Path
import sys
import time

# Add scripts directory to path for imports
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from parse_vsp_outputs import parse_all_vsp_outputs
from inject_openfoam_dicts import inject_all_openfoam_dicts


class SingleAnglePipeline:
    def __init__(self, base_dir: Path, angle: float, case_name: str):
        self.base_dir = base_dir
        self.angle = angle
        self.case_name = case_name
        
        # Directory structure
        self.geometry_dir = base_dir / "geometry"
        self.geometry_source = self.geometry_dir / "source"
        self.geometry_outputs = self.geometry_dir / "outputs"
        self.template_dir = base_dir / "templates" / "drone_template"
        self.cases_dir = base_dir / "cases"
        self.case_dir = self.cases_dir / case_name
        self.scripts_dir = base_dir / "scripts"
        self.vsp_utils = self.scripts_dir / "vsp_utils"
        
        # VSP executable (adjust path as needed)
        self.vsp_exe = Path("C:/Users/Jackson/Desktop/ZZ_Software Downloads/OpenVSP-3.46.0-win64/vsp.exe")
        
        # File paths
        self.vsp_file = self.geometry_source / "baseline.vsp3"
        self.des_file = self.geometry_source / "baseline.des"
        
    def run_step(self, step_name: str, func):
        """Run a pipeline step with error handling and timing"""
        print(f"\n{'='*60}")
        print(f"STEP: {step_name}")
        print(f"{'='*60}")
        start = time.time()
        
        try:
            func()
            elapsed = time.time() - start
            print(f"✓ {step_name} completed in {elapsed:.1f}s")
            return True
        except Exception as e:
            print(f"✗ {step_name} FAILED: {e}")
            raise
    
    def step1_export_vsp_geometry(self):
        """Run VSP batch scripts to export geometry and extract properties"""
        print("Exporting STL geometry...")
        
        # Export geometry (STL)
        export_geom_script = self.vsp_utils / "export_geom.vspscript"
        cmd = [
            str(self.vsp_exe),
            "-batch",
            str(self.vsp_file),
            "-des", str(self.des_file),
            "-script", str(export_geom_script)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stderr)
            raise RuntimeError("VSP export_geom failed")
        print(result.stdout)
        
        # Export mass properties
        print("\nExporting mass properties...")
        export_mass_script = self.vsp_utils / "export_mass_props.vspscript"
        cmd = [
            str(self.vsp_exe),
            "-batch",
            str(self.vsp_file),
            "-des", str(self.des_file),
            "-script", str(export_mass_script)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stderr)
            raise RuntimeError("VSP export_mass_props failed")
        print(result.stdout)
        
        # Export frontal area
        print("\nExporting frontal area...")
        export_area_script = self.vsp_utils / "export_frontal_area.vspscript"
        cmd = [
            str(self.vsp_exe),
            "-batch",
            str(self.vsp_file),
            "-des", str(self.des_file),
            "-script", str(export_area_script)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stderr)
            raise RuntimeError("VSP export_frontal_area failed")
        print(result.stdout)
        
        # Export wing references (assume you have this script)
        print("\nExporting wing references...")
        export_wing_script = self.vsp_utils / "export_wing_refs.vspscript"
        if export_wing_script.exists():
            cmd = [
                str(self.vsp_exe),
                "-batch",
                str(self.vsp_file),
                "-des", str(self.des_file),
                "-script", str(export_wing_script)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(result.stderr)
                raise RuntimeError("VSP export_wing_refs failed")
            print(result.stdout)
    
    def step2_parse_vsp_data(self):
        """Parse VSP outputs to get reference values"""
        print("Parsing VSP output files...")
        
        massprops = self.geometry_outputs / "baseline_massprops.csv"
        frontal_area = self.geometry_outputs / "baseline_frontal_area.csv"
        wing_refs = self.geometry_outputs / "wing_refs.csv"
        
        self.vsp_data = parse_all_vsp_outputs(massprops, frontal_area, wing_refs)
        
        print(f"  CG: ({self.vsp_data['cg_x']:.6f}, {self.vsp_data['cg_y']:.6f}, {self.vsp_data['cg_z']:.6f}) m")
        print(f"  Reference Area: {self.vsp_data['area_ref']:.6f} m²")
        print(f"  Reference Chord: {self.vsp_data['chord_ref']:.6f} m")
        print(f"  Reference Span: {self.vsp_data['span_ref']:.6f} m")
    
    def step3_setup_case(self):
        """Copy template and set up OpenFOAM case"""
        print(f"Setting up OpenFOAM case at {self.case_dir}...")
        
        # Remove old case if exists
        if self.case_dir.exists():
            print(f"  Removing existing case...")
            shutil.rmtree(self.case_dir)
        
        # Copy template
        print(f"  Copying template from {self.template_dir}...")
        shutil.copytree(self.template_dir, self.case_dir)
        
        # Copy STL to constant/triSurface/
        tri_surface_dir = self.case_dir / "constant" / "triSurface"
        tri_surface_dir.mkdir(parents=True, exist_ok=True)
        
        stl_source = self.geometry_outputs / "current.stl"
        stl_dest = tri_surface_dir / "current.stl"
        
        print(f"  Copying STL: {stl_source} -> {stl_dest}")
        shutil.copy(stl_source, stl_dest)
        
        # Inject reference values into OpenFOAM dictionaries
        print("  Injecting reference values into OpenFOAM dictionaries...")
        inject_all_openfoam_dicts(self.case_dir, self.vsp_data, "current.stl")
    
    def step4_set_angle_of_attack(self):
        """Modify 0/U to set angle of attack"""
        print(f"Setting angle of attack to {self.angle}°...")
        
        import math
        u_file = self.case_dir / "0" / "U"
        
        # Read U file
        content = u_file.read_text()
        
        # Calculate velocity components
        # Assume freestream velocity = 25 m/s (adjust as needed)
        v_mag = 25.0
        angle_rad = math.radians(self.angle)
        u_x = v_mag * math.cos(angle_rad)
        u_z = v_mag * math.sin(angle_rad)
        
        # Replace internalField uniform velocity
        import re
        pattern = r'internalField\s+uniform\s+\([^)]+\);'
        replacement = f'internalField   uniform ({u_x:.6f} 0 {u_z:.6f});'
        content = re.sub(pattern, replacement, content)
        
        # Replace inlet boundary condition
        # Find the inlet patch and update its value
        # This is a simplified approach - adjust regex as needed for your case
        inlet_pattern = r'(inlet\s*\{[^}]*value\s+uniform\s+)\([^)]+\);'
        inlet_replacement = rf'\1({u_x:.6f} 0 {u_z:.6f});'
        content = re.sub(inlet_pattern, inlet_replacement, content, flags=re.DOTALL)
        
        u_file.write_text(content)
        print(f"  Velocity: ({u_x:.3f}, 0, {u_z:.3f}) m/s")
    
    def step5_generate_mesh(self):
        """Run surfaceFeatures and snappyHexMesh"""
        print("Generating mesh...")
        
        # Extract surface features
        print("  Running surfaceFeatures...")
        result = subprocess.run(
            ["surfaceFeatures"],
            cwd=self.case_dir,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print(result.stderr)
            raise RuntimeError("surfaceFeatures failed")
        
        # Run snappyHexMesh
        print("  Running snappyHexMesh...")
        result = subprocess.run(
            ["snappyHexMesh", "-overwrite"],
            cwd=self.case_dir,
            capture_output=True,
            text=True
        )
        
        # Write log
        log_file = self.case_dir / "log.snappyHexMesh"
        log_file.write_text(result.stdout + "\n" + result.stderr)
        
        if result.returncode != 0:
            print(result.stderr)
            raise RuntimeError("snappyHexMesh failed")
        
        print("  Mesh generated successfully")
    
    def step6_run_solver(self):
        """Run OpenFOAM solver"""
        print("Running CFD solver...")
        
        # Determine solver (simpleFoam, rhoSimpleFoam, etc.)
        # Check controlDict for application
        control_dict = self.case_dir / "system" / "controlDict"
        content = control_dict.read_text()
        
        solver = "simpleFoam"  # Default
        import re
        match = re.search(r'application\s+(\w+);', content)
        if match:
            solver = match.group(1)
        
        print(f"  Using solver: {solver}")
        
        result = subprocess.run(
            [solver],
            cwd=self.case_dir,
            capture_output=True,
            text=True
        )
        
        # Write log
        log_file = self.case_dir / f"log.{solver}"
        log_file.write_text(result.stdout + "\n" + result.stderr)
        
        if result.returncode != 0:
            print(result.stderr)
            raise RuntimeError(f"{solver} failed")
        
        print(f"  Solver completed")
    
    def step7_extract_results(self):
        """Extract force coefficients from postProcessing"""
        print("Extracting force coefficients...")
        
        # Find latest force coefficient file
        postproc_dir = self.case_dir / "postProcessing" / "forceCoeffs"
        
        if not postproc_dir.exists():
            raise RuntimeError("No forceCoeffs output found")
        
        # Get latest time directory
        time_dirs = sorted([d for d in postproc_dir.iterdir() if d.is_dir()])
        if not time_dirs:
            raise RuntimeError("No time directories in forceCoeffs")
        
        latest_time = time_dirs[-1]
        coeff_file = latest_time / "coefficient.dat"
        
        if not coeff_file.exists():
            raise RuntimeError(f"coefficient.dat not found in {latest_time}")
        
        # Parse last line of coefficient file
        with open(coeff_file, 'r') as f:
            lines = [line for line in f if not line.strip().startswith('#')]
            if not lines:
                raise RuntimeError("No data in coefficient.dat")
            
            last_line = lines[-1].split()
            
            # Typical format: Time Cd Cs Cl CmRoll CmPitch CmYaw Cd(f) Cd(r) Cs(f) Cs(r) Cl(f) Cl(r)
            self.results = {
                'angle': self.angle,
                'Cd': float(last_line[1]),
                'Cs': float(last_line[2]),
                'Cl': float(last_line[3]),
                'CmPitch': float(last_line[5]),
            }
            
            # Calculate L/D
            if self.results['Cd'] > 0:
                self.results['L/D'] = self.results['Cl'] / self.results['Cd']
            else:
                self.results['L/D'] = 0.0
        
        print(f"\n  Results at α={self.angle}°:")
        print(f"    Cl = {self.results['Cl']:.6f}")
        print(f"    Cd = {self.results['Cd']:.6f}")
        print(f"    L/D = {self.results['L/D']:.3f}")
        print(f"    Cm = {self.results['CmPitch']:.6f}")
        
        return self.results
    
    def run(self):
        """Execute full pipeline"""
        print(f"\n{'#'*60}")
        print(f"SINGLE ANGLE CFD PIPELINE")
        print(f"Angle: {self.angle}°")
        print(f"Case: {self.case_name}")
        print(f"{'#'*60}")
        
        self.run_step("1. Export VSP Geometry", self.step1_export_vsp_geometry)
        self.run_step("2. Parse VSP Data", self.step2_parse_vsp_data)
        self.run_step("3. Setup OpenFOAM Case", self.step3_setup_case)
        self.run_step("4. Set Angle of Attack", self.step4_set_angle_of_attack)
        self.run_step("5. Generate Mesh", self.step5_generate_mesh)
        self.run_step("6. Run CFD Solver", self.step6_run_solver)
        results = self.run_step("7. Extract Results", self.step7_extract_results)
        
        print(f"\n{'#'*60}")
        print(f"PIPELINE COMPLETE")
        print(f"{'#'*60}")
        
        return results


def main():
    parser = argparse.ArgumentParser(description="Run single-angle CFD pipeline")
    parser.add_argument("--angle", type=float, required=True, help="Angle of attack in degrees")
    parser.add_argument("--case-name", type=str, required=True, help="Name for OpenFOAM case")
    parser.add_argument("--base-dir", type=str, default="/home/jwhite/JWsim/OpenFOAM_Optimization_01",
                       help="Base project directory")
    
    args = parser.parse_args()
    
    base_dir = Path(args.base_dir)
    
    pipeline = SingleAnglePipeline(base_dir, args.angle, args.case_name)
    results = pipeline.run()
    
    print(f"\nFinal Results:")
    print(f"  Angle: {results['angle']}°")
    print(f"  Cl: {results['Cl']:.6f}")
    print(f"  Cd: {results['Cd']:.6f}")
    print(f"  L/D: {results['L/D']:.3f}")
    print(f"  Cm: {results['CmPitch']:.6f}")


if __name__ == "__main__":
    main()
