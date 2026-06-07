"""
Generate thesis figures from benchmark_summary.csv.

Produces fig_solve_time.png and fig_coverage.png in the backend folder.

Usage (from backend folder, after benchmark.py has produced the CSV):
    pip install matplotlib    # one-time, if not installed
    python scripts/make_charts.py
"""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

with open("benchmark_summary.csv", newline="") as f:
    rows = list(csv.DictReader(f))

flights   = [int(r["flights"]) for r in rows]
sizes     = [r["size"] for r in rows]
time_mean = [float(r["time_mean_s"]) for r in rows]
time_std  = [float(r["time_std_s"]) for r in rows]
cov_mean  = [float(r["coverage_mean_pct"]) for r in rows]
cov_std   = [float(r["coverage_std_pct"]) for r in rows]

# Figure 1: solve time vs size
plt.figure(figsize=(7, 4.5))
plt.errorbar(flights, time_mean, yerr=time_std, marker="o", capsize=4,
             color="#378ADD", linewidth=2, markersize=7)
for x, y, s in zip(flights, time_mean, sizes):
    plt.annotate(f"{s}\n{y:.1f}s", (x, y), textcoords="offset points",
                 xytext=(10, 6), fontsize=9)
plt.xlabel("Number of flights")
plt.ylabel("Solve time (seconds)")
plt.title("GA solve time vs problem size (mean ± std, n=5)")
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("fig_solve_time.png", dpi=150)
plt.close()

# Figure 2: coverage vs size
plt.figure(figsize=(7, 4.5))
plt.errorbar(flights, cov_mean, yerr=cov_std, marker="s", capsize=4,
             color="#2e8b57", linewidth=2, markersize=7)
for x, y, s in zip(flights, cov_mean, sizes):
    plt.annotate(f"{s}\n{y:.1f}%", (x, y), textcoords="offset points",
                 xytext=(10, 6), fontsize=9)
plt.xlabel("Number of flights")
plt.ylabel("Coverage (%)")
plt.title("Solution coverage vs problem size (mean ± std, n=5)")
plt.ylim(0, 100)
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("fig_coverage.png", dpi=150)
plt.close()

print("Wrote fig_solve_time.png and fig_coverage.png")