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

## Export/setup only (no meshing/solver)
python3 scripts/run_single_alpha.py --alpha 8 --case-name alpha_8_export_only --no-mesh
