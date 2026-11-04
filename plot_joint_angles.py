
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


root = Path(__file__).resolve().parent

csv_path = root / "outputs/joint_angles.csv"
output_path = root / "outputs/joint_angles_plot.png"

df = pd.read_csv(csv_path)

df["time_s"] = df["timestamp_ms"] / 1000

fig, ax = plt.subplots(figsize=(12, 5))

ax.plot(
    df["time_s"],
    df["right_elbow_angle"],
    label="Right Elbow",
    marker=".",
    markersize=3,
)

ax.plot(
    df["time_s"],
    df["right_knee_angle"],
    label="Right Knee",
    marker=".",
    markersize=3,
)

# Previously annotated release: frame 49, 1.633 s
release_time = 1.633

ax.axvline(
    release_time,
    linestyle="--",
    label="Ball Release",
)

ax.set_title("Shooting Arm and Knee Angles Over Time")
ax.set_xlabel("Time (seconds)")
ax.set_ylabel("Joint Angle (degrees)")
ax.set_ylim(0, 180)
ax.legend()
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(output_path, dpi=180)
plt.show()

print(f"Plot saved to: {output_path}")
