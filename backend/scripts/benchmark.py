"""
Scalability benchmark for FlightRotate.

For each dataset size (small / medium / large) a fixed problem instance is
generated (data seed = 42), then the genetic algorithm is run REPS times with
different GA seeds. We report mean / std / min / max for the key KPIs and write
per-run rows to benchmark_results.csv plus an aggregated benchmark_summary.csv.

This is the data source for the thesis "Experimental Results" chapter:
solution quality and solve time as the problem size grows.

Prerequisite: the backend must be running (ideally WITHOUT --reload for clean
timing):
    uvicorn api.main:app --port 8000

Usage (from the backend folder):
    python scripts/benchmark.py
    python scripts/benchmark.py --reps 3
"""
import argparse
import csv
import json
import statistics
import urllib.request

BASE = "http://localhost:8000/api"
SIZES = ["small", "medium", "large"]
DATA_SEED = 42  # fixed instance per size -> reproducible problem


def _post(path, body, timeout=300):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _get(path, timeout=60):
    req = urllib.request.Request(BASE + path, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _check_backend():
    try:
        _get("/runs")
    except Exception:
        print("ERROR: Cannot reach backend at http://localhost:8000.")
        print("Start it first:  uvicorn api.main:app --port 8000")
        raise SystemExit(1)


def run_once(ga_seed):
    """Trigger one GA optimization and return its KPIs."""
    resp = _post("/optimize", {
        "algorithm": "genetic",
        "weights": {"coverage": 0.5, "idle": 0.25, "fuel": 0.25},
        "seed": ga_seed,
    })
    summary = _get(f"/runs/{resp['run_id']}")
    return summary["kpi"]


def stats(vals):
    mean = statistics.mean(vals)
    std = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return mean, std, min(vals), max(vals)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reps", type=int, default=5)
    args = parser.parse_args()

    _check_backend()

    # Warm up so solver/library imports don't inflate the first timed run.
    print("Warming up (loading solver modules)...")
    _post("/sample", {"size": "small", "seed": DATA_SEED, "clear_existing": True})
    try:
        run_once(ga_seed=999)
    except Exception:
        pass

    rows = []        # per-run rows
    summary = []     # aggregated per size

    for size in SIZES:
        print(f"\n=== Size: {size} ===")
        gen = _post("/sample", {"size": size, "seed": DATA_SEED, "clear_existing": True})
        total, ac = gen["flights_generated"], gen["aircraft_generated"]
        print(f"Generated {total} flights, {ac} aircraft. Running {args.reps} reps...")

        acc = {k: [] for k in
               ["coverage", "total_idle_minutes", "total_fuel_kg",
                "fuel_cost_usd", "solve_time_seconds", "assigned_flights"]}

        for rep in range(1, args.reps + 1):
            kpi = run_once(ga_seed=rep)
            for k in acc:
                acc[k].append(kpi[k])
            rows.append({
                "size": size, "rep": rep, "flights": total, "aircraft": ac,
                "coverage_pct": round(kpi["coverage"] * 100, 2),
                "assigned": kpi["assigned_flights"],
                "idle_minutes": kpi["total_idle_minutes"],
                "fuel_kg": round(kpi["total_fuel_kg"], 1),
                "fuel_cost_usd": round(kpi["fuel_cost_usd"], 2),
                "solve_time_s": round(kpi["solve_time_seconds"], 2),
            })
            print(f"  rep {rep}: coverage {kpi['coverage']*100:5.1f}%  "
                  f"idle {kpi['total_idle_minutes']:>6}  "
                  f"fuel {kpi['total_fuel_kg']:>8.0f}kg  "
                  f"time {kpi['solve_time_seconds']:5.1f}s")

        cov_m, cov_s, _, _ = stats([v * 100 for v in acc["coverage"]])
        idle_m, idle_s, _, _ = stats(acc["total_idle_minutes"])
        fuel_m, fuel_s, _, _ = stats(acc["total_fuel_kg"])
        cost_m, cost_s, _, _ = stats(acc["fuel_cost_usd"])
        t_m, t_s, t_lo, t_hi = stats(acc["solve_time_seconds"])

        summary.append({
            "size": size, "flights": total, "aircraft": ac, "reps": args.reps,
            "coverage_mean_pct": round(cov_m, 2), "coverage_std_pct": round(cov_s, 2),
            "idle_mean_min": round(idle_m, 1), "idle_std_min": round(idle_s, 1),
            "fuel_mean_kg": round(fuel_m, 1), "fuel_std_kg": round(fuel_s, 1),
            "cost_mean_usd": round(cost_m, 2), "cost_std_usd": round(cost_s, 2),
            "time_mean_s": round(t_m, 2), "time_std_s": round(t_s, 2),
            "time_min_s": round(t_lo, 2), "time_max_s": round(t_hi, 2),
        })

    # --- Write CSVs ---
    if rows:
        with open("benchmark_results.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    if summary:
        with open("benchmark_summary.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
            w.writeheader()
            w.writerows(summary)

    # --- Print summary table ---
    print("\n\n==================== SCALABILITY SUMMARY ====================")
    print(f"{'Size':<8}{'Flights':<9}{'AC':<5}{'Coverage':<16}"
          f"{'Idle(min)':<16}{'Fuel(kg)':<18}{'Solve(s)':<14}")
    print("-" * 90)
    for s in summary:
        print(f"{s['size']:<8}{s['flights']:<9}{s['aircraft']:<5}"
              f"{s['coverage_mean_pct']:.1f}±{s['coverage_std_pct']:.1f}%".ljust(16)
              + f"{s['idle_mean_min']:.0f}±{s['idle_std_min']:.0f}".ljust(16)
              + f"{s['fuel_mean_kg']:.0f}±{s['fuel_std_kg']:.0f}".ljust(18)
              + f"{s['time_mean_s']:.1f}±{s['time_std_s']:.1f}".ljust(14))
    print("=" * 90)
    print("\nWritten: benchmark_results.csv (per-run)  +  benchmark_summary.csv (aggregated)")
    print("Use these for the thesis Experimental Results charts.")


if __name__ == "__main__":
    main()