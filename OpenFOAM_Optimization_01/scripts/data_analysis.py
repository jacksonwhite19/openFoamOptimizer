import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os

# Configuration
angles = [0, 2, 4, 6, 8, 10]
l_ref = 0.137879  # Mean Aerodynamic Chord (MAC)

data = []

for a in angles:
    path = f"results_alpha_{a}/postProcessing/forceCoeffs1/0/forceCoeffs.dat"
    if os.path.exists(path):
        # Read the last line of the data file
        df = pd.read_csv(path, sep='\s+', comment='#', header=None)
        last_row = df.iloc[-1]
        # Columns: Time(0), Cm(1), Cd(2), Cl(3)
        data.append({'alpha': a, 'Cm': last_row[1], 'Cd': last_row[2], 'Cl': last_row[3]})

df_results = pd.DataFrame(data)
df_results['L_D'] = df_results['Cl'] / df_results['Cd']

# 1. Calculate Static Margin (SM)
# SM = - (dCm / dCl)
coeffs = np.polyfit(df_results['Cl'], df_results['Cm'], 1)
static_margin = -coeffs[0] * 100  # As a percentage of MAC

# ... existing code above ...

# 2. Plotting L/D Polar
plt.figure(figsize=(12, 5))

# Plot 1: L/D vs Alpha
plt.subplot(1, 2, 1)
# Adding .values converts Pandas series to a format Matplotlib likes
plt.plot(df_results['alpha'].values, df_results['L_D'].values, 'o-', color='green')
plt.title('Efficiency (L/D) vs Alpha')
plt.xlabel('Angle of Attack (deg)')
plt.ylabel('L/D Ratio')
plt.grid(True)

# Plot 2: Lift Polar (Cl vs Cd)
plt.subplot(1, 2, 2)
# Adding .values here too
plt.plot(df_results['Cd'].values, df_results['Cl'].values, 'o-', color='blue')
plt.title('Lift Polar (Cl vs Cd)')
plt.xlabel('Cd (Drag)')
plt.ylabel('Cl (Lift)')
plt.grid(True)

plt.tight_layout()
plt.savefig('drone_performance_results.png')
print("Plots saved to drone_performance_results.png")

# Calculate and print Static Margin
print(f"Calculated Static Margin: {static_margin:.2f}% of MAC")

# Print the table for your notes
print("\n--- Summary Table ---")
print(df_results[['alpha', 'Cl', 'Cd', 'L_D', 'Cm']])
print(f"Calculated Static Margin: {static_margin:.2f}% of MAC")