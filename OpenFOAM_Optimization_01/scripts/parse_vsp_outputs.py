"""
VSP Output Parser
Extracts CG, reference area, span, and chord from OpenVSP analysis outputs.
"""

import csv
import argparse
from pathlib import Path
from typing import Dict, Optional


def parse_mass_properties(csv_path: Path) -> Dict[str, float]:
    """
    Parse MassProp CSV to extract total CG coordinates.
    
    Args:
        csv_path: Path to baseline_massprops.csv
        
    Returns:
        Dictionary with cg_x, cg_y, cg_z in meters (converted from mm)
    """
    with open(csv_path, 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 4 and row[0] == 'Total_CG':
                # Total_CG row: ['Total_CG', x, y, z] (in mm)
                return {
                    'cg_x': float(row[1]) / 1000.0,  # mm to m
                    'cg_y': float(row[2]) / 1000.0,
                    'cg_z': float(row[3]) / 1000.0
                }
    
    raise ValueError(f"Could not find Total_CG in {csv_path}")


def parse_frontal_area(csv_path: Path) -> Dict[str, float]:
    """
    Parse Projection CSV to extract frontal area.
    
    Args:
        csv_path: Path to baseline_frontal_area.csv
        
    Returns:
        Dictionary with area_frontal in m²
    """
    with open(csv_path, 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 2 and row[0] == 'Area':
                area_mm2 = float(row[1])
                return {
                    'area_frontal': area_mm2 / 1_000_000.0  # mm² to m²
                }
    
    raise ValueError(f"Could not find Area in {csv_path}")


def parse_wing_references(csv_path: Path) -> Dict[str, float]:
    """
    Parse wing reference CSV to extract Aref, bref (span), lref (chord).
    
    Args:
        csv_path: Path to wing_refs.csv
        
    Returns:
        Dictionary with area_ref, span_ref, chord_ref in meters
    """
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        row = next(reader)  # Only one data row expected
        
        return {
            'area_ref': float(row['Aref_m2']),
            'span_ref': float(row['bref_m']),
            'chord_ref': float(row['lref_m'])
        }


def parse_all_vsp_outputs(
    massprops_path: Path,
    frontal_area_path: Path,
    wing_refs_path: Path
) -> Dict[str, float]:
    """
    Parse all VSP outputs and combine into single dictionary.
    
    Args:
        massprops_path: Path to baseline_massprops.csv
        frontal_area_path: Path to baseline_frontal_area.csv
        wing_refs_path: Path to wing_refs.csv
        
    Returns:
        Combined dictionary with all reference values
    """
    result = {}
    
    # Parse each file
    result.update(parse_mass_properties(massprops_path))
    result.update(parse_frontal_area(frontal_area_path))
    result.update(parse_wing_references(wing_refs_path))
    
    return result


def main():
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Parse VSP CSV outputs into normalized SI units.")
    parser.add_argument(
        "--geometry-outputs",
        type=Path,
        default=Path("geometry/outputs"),
        help="Directory containing baseline_massprops.csv, baseline_frontal_area.csv, and wing_refs.csv",
    )
    parser.add_argument(
        "--massprops",
        type=Path,
        default=None,
        help="Optional explicit path to baseline_massprops.csv",
    )
    parser.add_argument(
        "--frontal-area",
        type=Path,
        default=None,
        help="Optional explicit path to baseline_frontal_area.csv",
    )
    parser.add_argument(
        "--wing-refs",
        type=Path,
        default=None,
        help="Optional explicit path to wing_refs.csv",
    )
    args = parser.parse_args()

    geometry_outputs = args.geometry_outputs

    massprops = args.massprops or (geometry_outputs / "baseline_massprops.csv")
    frontal_area = args.frontal_area or (geometry_outputs / "baseline_frontal_area.csv")
    wing_refs = args.wing_refs or (geometry_outputs / "wing_refs.csv")
    
    # Parse all outputs
    vsp_data = parse_all_vsp_outputs(massprops, frontal_area, wing_refs)
    
    # Print results
    print("VSP Reference Data:")
    print(f"  CG: ({vsp_data['cg_x']:.6f}, {vsp_data['cg_y']:.6f}, {vsp_data['cg_z']:.6f}) m")
    print(f"  Frontal Area: {vsp_data['area_frontal']:.6f} m²")
    print(f"  Reference Area: {vsp_data['area_ref']:.6f} m²")
    print(f"  Reference Span: {vsp_data['span_ref']:.6f} m")
    print(f"  Reference Chord: {vsp_data['chord_ref']:.6f} m")
    
    return vsp_data


if __name__ == "__main__":
    main()
