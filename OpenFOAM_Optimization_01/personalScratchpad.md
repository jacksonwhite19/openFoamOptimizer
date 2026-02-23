## Steps:
- generate STL
- check STL with surfaceCheck current.stl
- convert units from mm to m
    - surfaceTransformPoints "scale=(0.001 0.001 0.001)" current.stl current_m.stl
- copy geometry to constant > geometry folder 
- update snappyHexMeshDict
- Update surfaceFeaturesDict - reference motorbike ex. and change file name
- Clean and run mesh:
```
cd ~/JWsim/OpenFOAM_Optimization_01/templates/drone_template

# Clean
./Allclean

# Step 1: Background mesh
blockMesh

# Step 2: Extract features
surfaceFeatures

# Step 3: Snap mesh to geometry
snappyHexMesh -overwrite

# Step 4: Check mesh quality
checkMesh
```
- Add force coefficients function (update from motorbike)
- update Center of Rotation (CofR) in force coeffs
    - is this the CG? if so, will need to update from openvsp every iterations

# Step 5: Set initial conditions
- set initial conditions. go to 0, include, initial conditions
    - flow velocity, m/s, xyz components
- use openvsp analysis projected area to find lRef and Aref
