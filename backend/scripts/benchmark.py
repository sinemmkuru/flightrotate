"""
Scalability + GA-vs-CP-SAT benchmark for FlightRotate.

For each (size, num_days) instance a fixed problem is generated (data seed=42),
then:
  - the genetic algorithm is run REPS times with different GA seeds
    (mean / std / min / max reported), and
  - the CP-SAT exact solver is run once with a time limit, recording its
    solve status (OPTIMAL / FEASIBLE / UNKNOWN) so we can see where the exact
    method stops being practical.

This is the data source for the thesis "Experimental Results" chapter:
solution quality and solve time as the problem grows, and the GA (heuristic)
vs CP-SAT (exact) trade-off across scales.

Outputs:
  - benchmark_results.csv : one row per run (every GA seed + each CP-SAT run)
  - benchmark_summary.csv : one row per (size, days) with GA mean/std beside
                            the CP-SAT result

Prerequisite: backend running, ideally WITHOUT --reload for clean timing:
    uvicorn api.main:app --port 8000
(The GA is deterministic per seed, so PYTHONHASHSEED is NOT required.)

Usage (from the backend folder):
    python scripts/benchmark.py
    python scripts/benchmark.py --reps 5 --cpsat-time-limit 30
    python scripts/benchmark.py --quick          # small/medium only, fast
"""
import argparse
import csv
import json
import statistics
import urllib.request

BASE = "http://localhost:8000/api"
DATA_SEED = 42          # fixed instance per (size, days) -> reproducible problem
OPTIMIZE_TIMEOUT = 1800  # seconds; GA on large multi-day instances can be slow

# (size, num_days) instances. Kept runnable: GA cost grows with flight count,
# so large is not pushed out to a full month by default.
FULL_GRID = [
    ("small", 1), ("small", 7), ("small", 30),
    ("medium", 1), ("medium", 7),
    ("large", 1), ("large", 7),
]
QUICK_GRID = [
    ("small", 1), ("small", 7),
    ("medium", 1),
]

KPI_KEYS = [
    "coverage", "total_idle_minutes", "total_fuel_kg",
    "fuel_cost_usd", "solve_time_seconds", "assigned_flights",
]


def _post(path, body, timeout=300):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _get(path, timeout=120):
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


def _parse_status(message):
    """Extract the CP-SAT solve status from the optimize message.

    The message ends with a solver label, e.g. '... [cp_sat (optimal)]' or
    '... [genetic]'. Returns the word inside the parentheses ('optimal',
    'feasible', 'unknown'), or '' when there is none (e.g. genetic).
    """
    if "(" in message and ")" in message:
        return message.rsplit("(", 1)[1].split(")")[0].strip()
    return ""


def run_solver(algorithm, seed=None, time_limit=None):
    """Trigger one optimization; return (kpi_dict, solve_status)."""
    body = {
        "algorithm": algorithm,
        "weights": {"coverage": 0.5, "idle": 0.25, "robustness": 0.25},
    }
    if seed is not None:
        body["seed"] = seed
    if time_limit is not None:
        body["time_limit_seconds"] = time_limit

    resp = _post("/optimize", body, timeout=OPTIMIZE_TIMEOUT)
    kpi = _get(f"/runs/{resp['run_id']}")["kpi"]
    status = _parse_status(resp.get("message", ""))
    return kpi, status


def stats(vals):
    mean = statistics.mean(vals)
    std = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return mean, std, min(vals), max(vals)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reps", type=int, default=3,
                        help="number of GA seeds per instance")
    parser.add_argument("--cpsat-time-limit", type=float, default=30.0,
                        help="CP-SAT time limit per instance (seconds)")
    parser.add_argument("--quick", action="store_true",
                        help="use a small, fast grid (small/medium only)")
    args = parser.parse_args()

    grid = QUICK_GRID if args.quick else FULL_GRID

    _check_backend()

    # Warm up so solver/library imports don't inflate the first timed run.
    print("Warming up (loading solver modules)...")
    _post("/sample", {"size": "small", "seed": DATA_SEED, "num_days": 1,
                      "clear_existing": True})
    try:
        run_solver("genetic", seed=999)
        run_solver("cp_sat", time_limit=5.0)
    except Exception:
        pass

    rows = []        # per-run rows (every GA seed + each CP-SAT run)
    summary = []     # one aggregated row per (size, days)

    for size, days in grid:
        print(f"\n=== {size} x {days} day(s) ===")
        gen = _post("/sample", {"size": size, "seed": DATA_SEED,
                                "num_days": days, "clear_existing": True})
        total, ac = gen["flights_generated"], gen["aircraft_generated"]
        print(f"Generated {total} flights, {ac} aircraft. "
              f"GA reps={args.reps}, CP-SAT limit={args.cpsat_time_limit}s")

        # --- GA: REPS seeds ---
        ga_acc = {k: [] for k in KPI_KEYS}
        for rep in range(1, args.reps + 1):
            kpi, _ = run_solver("genetic", seed=rep)
            for k in KPI_KEYS:
                ga_acc[k].append(kpi[k])
            rows.append({
                "size": size, "days": days, "flights": total, "aircraft": ac,
                "solver": "genetic", "seed": rep,
                "coverage_pct": round(kpi["coverage"] * 100, 2),
                "assigned": kpi["assigned_flights"],
                "idle_minutes": kpi["total_idle_minutes"],
                "fuel_kg": round(kpi["total_fuel_kg"], 1),
                "fuel_cost_usd": round(kpi["fuel_cost_usd"], 2),
                "solve_time_s": round(kpi["solve_time_seconds"], 2),
                "status": "",
            })
            print(f"  GA   seed {rep}: cov {kpi['coverage']*100:5.1f}%  "
                  f"idle {kpi['total_idle_minutes']:>7}  "
                  f"fuel {kpi['total_fuel_kg']:>9.0f}kg  "
                  f"time {kpi['solve_time_seconds']:7.1f}s")

        # --- CP-SAT: one run with a time limit ---
        cp_kpi, cp_status = run_solver("cp_sat", time_limit=args.cpsat_time_limit)
        rows.append({
            "size": size, "days": days, "flights": total, "aircraft": ac,
            "solver": "cp_sat", "seed": "",
            "coverage_pct": round(cp_kpi["coverage"] * 100, 2),
            "assigned": cp_kpi["assigned_flights"],
            "idle_minutes": cp_kpi["total_idle_minutes"],
            "fuel_kg": round(cp_kpi["total_fuel_kg"], 1),
            "fuel_cost_usd": round(cp_kpi["fuel_cost_usd"], 2),
            "solve_time_s": round(cp_kpi["solve_time_seconds"], 2),
            "status": cp_status,
        })
        print(f"  CPSAT       : cov {cp_kpi['coverage']*100:5.1f}%  "
              f"idle {cp_kpi['total_idle_minutes']:>7}  "
              f"fuel {cp_kpi['total_fuel_kg']:>9.0f}kg  "
              f"time {cp_kpi['solve_time_seconds']:7.1f}s  [{cp_status}]")

        # --- Aggregate GA + pair with CP-SAT ---
        cov_m, cov_s, _, _ = stats([v * 100 for v in ga_acc["coverage"]])
        idle_m, idle_s, _, _ = stats(ga_acc["total_idle_minutes"])
        fuel_m, fuel_s, _, _ = stats(ga_acc["total_fuel_kg"])
        cost_m, cost_s, _, _ = stats(ga_acc["fuel_cost_usd"])
        t_m, t_s, _, _ = stats(ga_acc["solve_time_seconds"])

        summary.append({
            "size": size, "days": days, "flights": total, "aircraft": ac,
            "reps": args.reps,
            "ga_coverage_mean_pct": round(cov_m, 2),
            "ga_coverage_std_pct": round(cov_s, 2),
            "ga_idle_mean_min": round(idle_m, 1),
            "ga_fuel_mean_kg": round(fuel_m, 1),
            "ga_cost_mean_usd": round(cost_m, 2),
            "ga_time_mean_s": round(t_m, 2),
            "ga_time_std_s": round(t_s, 2),
            "cpsat_coverage_pct": round(cp_kpi["coverage"] * 100, 2),
            "cpsat_idle_min": cp_kpi["total_idle_minutes"],
            "cpsat_fuel_kg": round(cp_kpi["total_fuel_kg"], 1),
            "cpsat_cost_usd": round(cp_kpi["fuel_cost_usd"], 2),
            "cpsat_time_s": round(cp_kpi["solve_time_seconds"], 2),
            "cpsat_status": cp_status,
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

    # --- Print comparison table ---
    print("\n\n============================= GA vs CP-SAT =============================")
    print(f"{'Size':<7}{'Days':<5}{'Flts':<7}"
          f"{'GA cov':<13}{'GA time':<12}"
          f"{'CPSAT cov':<11}{'CPSAT t':<10}{'CPSAT status':<12}")
    print("-" * 78)
    for s in summary:
        ga_cov = f"{s['ga_coverage_mean_pct']:.1f}\u00b1{s['ga_coverage_std_pct']:.1f}%"
        ga_t = f"{s['ga_time_mean_s']:.1f}\u00b1{s['ga_time_std_s']:.1f}s"
        cp_cov = f"{s['cpsat_coverage_pct']:.1f}%"
        cp_t = f"{s['cpsat_time_s']:.1f}s"
        print(f"{s['size']:<7}{s['days']:<5}{s['flights']:<7}"
              f"{ga_cov:<13}{ga_t:<12}{cp_cov:<11}{cp_t:<10}{s['cpsat_status']:<12}")
    print("=" * 78)
    print("\nWritten: benchmark_results.csv (per-run)  +  benchmark_summary.csv")
    print("Use these for the thesis Experimental Results charts.")


if __name__ == "__main__":
    main()