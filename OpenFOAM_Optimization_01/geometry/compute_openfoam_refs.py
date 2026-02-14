import re
import csv
from pathlib import Path

# =========================
# USER SETTINGS
# =========================
DES_FILE = Path("geometry/source/baseline.des")
FUSE_HALF_MM = 120.0   # Half fuselage width (mm)
# Changed extension to .csv
OUTPUT_FILE = Path("geometry/outputs/wing_refs.csv") 

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

if span is None or tip_chord is None or taper is None:
    raise RuntimeError("Failed to extract Span / Tip_Chord / Taper from DES file")

# =========================
# GEOMETRY CALCULATIONS
# =========================
root_chord = tip_chord / taper
span_exposed_half = span - FUSE_HALF_MM

if span_exposed_half <= 0:
    raise RuntimeError("Wing fully buried — check fuselage width vs span")

# Metrics
bref = 2.0 * span_exposed_half / 1000.0
Sref = (span_exposed_half * (root_chord + tip_chord)) / 1e6
MAC = (2.0 / 3.0) * root_chord * (1 + taper + taper**2) / (1 + taper) / 1000.0

# =========================
# WRITE OUTPUT AS CSV
# =========================
# We use a dictionary format here for easy expansion later
data = {
    "Aref_m2": f"{Sref:.6f}",
    "bref_m": f"{bref:.6f}",
    "lref_m": f"{MAC:.6f}"
}

with open(OUTPUT_FILE, "w", newline="") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=data.keys())
    writer.writeheader()
    writer.writerow(data)

# =========================
# PRINT SUMMARY
# =========================
print(f"Computed OpenFOAM reference values saved to {OUTPUT_FILE}:")
print(f"  Aref: {data['Aref_m2']} | bref: {data['bref_m']} | lref: {data['lref_m']}")