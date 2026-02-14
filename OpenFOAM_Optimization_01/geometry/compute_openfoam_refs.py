import re
from pathlib import Path

# =========================
# USER SETTINGS
# =========================
DES_FILE = Path("geometry/source/baseline.des")
FUSE_HALF_MM = 120.0   # Half fuselage width (mm)
OUTPUT_FILE = Path("geometry/source/openfoam_refs.txt")

# =========================
# PARSE .DES FILE
# =========================
span = None
tip_chord = None
taper = None

pattern_val = re.compile(r":\s*([-+0-9.eE]+)")

with open(DES_FILE, "r") as f:
    for line in f:
        if "Lwing:XSec_1:Span" in line:
            span = float(pattern_val.search(line).group(1))

        elif "Lwing:XSec_1:Tip_Chord" in line:
            tip_chord = float(pattern_val.search(line).group(1))

        elif "Lwing:XSec_1:Taper" in line:
            taper = float(pattern_val.search(line).group(1))

# Safety check
if span is None or tip_chord is None or taper is None:
    raise RuntimeError("Failed to extract Span / Tip_Chord / Taper from DES file")

# =========================
# GEOMETRY CALCULATIONS
# =========================

# Root chord from taper
root_chord = tip_chord / taper

# Exposed half-span (remove buried portion)
span_exposed_half = span - FUSE_HALF_MM
if span_exposed_half <= 0:
    raise RuntimeError("Wing fully buried — check fuselage width vs span")

# --- bref (m)
bref = 2.0 * span_exposed_half / 1000.0

# --- Sref (m^2)
Sref = (span_exposed_half * (root_chord + tip_chord)) / 1e6

# --- MAC (m)
MAC = (2.0 / 3.0) * root_chord * (1 + taper + taper**2) / (1 + taper) / 1000.0

# =========================
# WRITE OUTPUT FOR OPENFOAM
# =========================
with open(OUTPUT_FILE, "w") as f:
    f.write("Reference values for OpenFOAM forceCoeffs\n")
    f.write("-----------------------------------------\n")
    f.write(f"Aref  {Sref:.6f};\n")
    f.write(f"bref  {bref:.6f};\n")
    f.write(f"lref  {MAC:.6f};\n")

# =========================
# PRINT SUMMARY
# =========================
print("Computed OpenFOAM reference values:")
print(f"  Span (bref) : {bref:.6f} m")
print(f"  Area (Sref) : {Sref:.6f} m^2")
print(f"  MAC  (cref) : {MAC:.6f} m")
print(f"\nWritten to: {OUTPUT_FILE}")
