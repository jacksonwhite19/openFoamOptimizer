"""
OpenFOAM Dictionary Injector
Updates forceCoeffs and snappyHexMeshDict with reference values from VSP.
"""

import re
import argparse
from pathlib import Path
from typing import Dict


def inject_force_coeffs(
    force_coeffs_path: Path,
    vsp_data: Dict[str, float],
    backup: bool = True
) -> None:
    """
    Update forceCoeffs dictionary with CG and reference values.
    
    Args:
        force_coeffs_path: Path to system/forceCoeffs file
        vsp_data: Dictionary with cg_x, cg_y, cg_z, area_ref, chord_ref, span_ref
        backup: If True, create .backup file before modifying
    """
    if backup:
        backup_path = force_coeffs_path.with_suffix('.backup')
        if not backup_path.exists():
            backup_path.write_text(force_coeffs_path.read_text())
    
    content = force_coeffs_path.read_text()
    
    # Update CG reference (OpenFOAM forceCoeffs usually uses CofR)
    # VSP: +X forward, +Y right, +Z up
    # OpenFOAM: +X streamwise, +Y lateral, +Z vertical (same conventions)
    cg_value = f'({vsp_data["cg_x"]:.6f} {vsp_data["cg_y"]:.6f} {vsp_data["cg_z"]:.6f})'
    cg_patterns = [
        (r'CenterOfRotation\s+\([^)]+\);', f'CenterOfRotation  {cg_value};'),
        (r'CofR\s+\([^)]+\);', f'CofR            {cg_value};'),
    ]
    for pattern, replacement in cg_patterns:
        if re.search(pattern, content):
            content = re.sub(pattern, replacement, content)
    
    # Update Aref (reference area)
    aref_pattern = r'Aref\s+[^;]+;'
    aref_replacement = f'Aref            {vsp_data["area_ref"]:.6f};'
    content = re.sub(aref_pattern, aref_replacement, content)
    
    # Update lref/lRef (reference chord)
    lref_replacement = f'lRef            {vsp_data["chord_ref"]:.6f};'
    lref_patterns = [
        r'lref\s+[^;]+;',
        r'lRef\s+[^;]+;',
    ]
    for pattern in lref_patterns:
        if re.search(pattern, content):
            content = re.sub(pattern, lref_replacement, content)
    
    # Update bref (reference span) - optional, not always in forceCoeffs
    bref_patterns = [
        r'bref\s+[^;]+;',
        r'bRef\s+[^;]+;',
    ]
    for pattern in bref_patterns:
        if re.search(pattern, content):
            bref_replacement = f'bRef            {vsp_data["span_ref"]:.6f};'
            content = re.sub(pattern, bref_replacement, content)
    
    # Write updated content
    force_coeffs_path.write_text(content)
    print(f"✓ Updated {force_coeffs_path}")


def inject_snappy_hex_mesh(
    snappy_dict_path: Path,
    vsp_data: Dict[str, float],
    stl_name: str = "current.stl",
    backup: bool = True
) -> None:
    """
    Update snappyHexMeshDict with geometry location and refinement center.
    
    Args:
        snappy_dict_path: Path to system/snappyHexMeshDict
        vsp_data: Dictionary with cg_x, cg_y, cg_z
        stl_name: Name of STL file (without path)
        backup: If True, create .backup file before modifying
    """
    if backup:
        backup_path = snappy_dict_path.with_suffix('.backup')
        if not backup_path.exists():
            backup_path.write_text(snappy_dict_path.read_text())
    
    content = snappy_dict_path.read_text()
    
    # Update locationInMesh - place point near CG but slightly offset to ensure it's inside
    # Use CG + small offset in vertical direction
    loc_pattern = r'locationInMesh\s+\([^)]+\);'
    loc_x = vsp_data["cg_x"]
    loc_y = vsp_data["cg_y"]
    loc_z = vsp_data["cg_z"] + 0.01  # 1cm above CG
    loc_replacement = f'locationInMesh ({loc_x:.6f} {loc_y:.6f} {loc_z:.6f});'
    content = re.sub(loc_pattern, loc_replacement, content)
    
    # Write updated content
    snappy_dict_path.write_text(content)
    print(f"✓ Updated {snappy_dict_path}")


def inject_all_openfoam_dicts(
    case_dir: Path,
    vsp_data: Dict[str, float],
    stl_name: str = "current.stl"
) -> None:
    """
    Update all OpenFOAM dictionaries in a case directory.
    
    Args:
        case_dir: Path to OpenFOAM case directory (contains system/)
        vsp_data: Dictionary with reference values from VSP
        stl_name: Name of STL file
    """
    system_dir = case_dir / "system"
    
    # Update forceCoeffs
    force_coeffs = system_dir / "forceCoeffs"
    if force_coeffs.exists():
        inject_force_coeffs(force_coeffs, vsp_data)
    else:
        print(f"⚠ Warning: {force_coeffs} not found")
    
    # Update snappyHexMeshDict
    snappy_dict = system_dir / "snappyHexMeshDict"
    if snappy_dict.exists():
        inject_snappy_hex_mesh(snappy_dict, vsp_data, stl_name)
    else:
        print(f"⚠ Warning: {snappy_dict} not found")


def main():
    """CLI entrypoint."""
    from parse_vsp_outputs import parse_all_vsp_outputs

    parser = argparse.ArgumentParser(description="Inject VSP-derived refs into OpenFOAM dictionaries.")
    parser.add_argument(
        "--geometry-outputs",
        type=Path,
        default=Path("geometry/outputs"),
        help="Directory containing VSP output CSV files",
    )
    parser.add_argument(
        "--case-dir",
        type=Path,
        default=Path("cases/test_runs/alpha_8"),
        help="OpenFOAM case directory containing system/forceCoeffs and system/snappyHexMeshDict",
    )
    parser.add_argument(
        "--stl-name",
        type=str,
        default="current.stl",
        help="STL filename used in the case",
    )
    args = parser.parse_args()

    geometry_outputs = args.geometry_outputs
    vsp_data = parse_all_vsp_outputs(
        geometry_outputs / "baseline_massprops.csv",
        geometry_outputs / "baseline_frontal_area.csv",
        geometry_outputs / "wing_refs.csv"
    )

    case_dir = args.case_dir
    inject_all_openfoam_dicts(case_dir, vsp_data, stl_name=args.stl_name)
    
    print("\nInjected values:")
    print(f"  CG: ({vsp_data['cg_x']:.6f}, {vsp_data['cg_y']:.6f}, {vsp_data['cg_z']:.6f}) m")
    print(f"  Aref: {vsp_data['area_ref']:.6f} m²")
    print(f"  lref: {vsp_data['chord_ref']:.6f} m")
    print(f"  bref: {vsp_data['span_ref']:.6f} m")


if __name__ == "__main__":
    main()
