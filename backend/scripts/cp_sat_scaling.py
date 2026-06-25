"""
Exact (CP-SAT) vs heuristic (GA) across problem sizes.

For each size, generates a fixed instance (seed=42) and runs BOTH algorithms
once, printing a head-to-head table. Demonstrates that CP-SAT is fast and
proven-optimal on small instances but saturates its time limit on large ones,
where the genetic algorithm remains the practical choice.

Watch the BACKEND console: run_cp_sat prints the solver status
(OPTIMAL = proven optimal; FEASIBLE = time limit hit before proving optimality).

Prerequisite: backend running on http://localhost:8000.
Usage (from the backend folder):  python scripts/cp_sat_scaling.py
"""
import json
import urllib.request

BASE = "http://localhost:8000/api"
SIZES = ["small", "medium", "large"]
DATA_SEED = 42


def _post(path, body, timeout=300):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _get(path, timeout=60):
    req = urllib.request.Request(BASE + path, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def run(algorithm, **extra):
    body = {"algorithm": algorithm,
            "weights": {"coverage": 0.5, "idle": 0.25, "robustness": 0.25}}
    body.update(extra)
    resp = _post("/optimize", body)
    return _get(f"/runs/{resp['run_id']}")["kpi"]


def main():
    rows = []
    for size in SIZES:
        gen = _post("/sample", {"size": size, "seed": DATA_SEED, "clear_existing": True})
        n = gen["flights_generated"]
        print(f"\n=== {size} ({n} flights) ===")
        ga = run("genetic", seed=1)
        print(f"  GA     : coverage {ga['coverage']*100:5.1f}%  time {ga['solve_time_seconds']:6.1f}s")
        cp = run("cp_sat")
        print(f"  CP-SAT : coverage {cp['coverage']*100:5.1f}%  time {cp['solve_time_seconds']:6.1f}s")
        rows.append((size, n, ga, cp))

    print("\n\n========== EXACT (CP-SAT) vs HEURISTIC (GA) ==========")
    print(f"{'Size':<8}{'Flights':<9}{'GA cov':<10}{'GA time':<10}{'CP cov':<10}{'CP time':<10}")
    print("-" * 60)
    for size, n, ga, cp in rows:
        print(f"{size:<8}{n:<9}"
              + f"{ga['coverage']*100:.1f}%".ljust(10)
              + f"{ga['solve_time_seconds']:.1f}s".ljust(10)
              + f"{cp['coverage']*100:.1f}%".ljust(10)
              + f"{cp['solve_time_seconds']:.1f}s".ljust(10))
    print("=" * 60)
    print("\nCheck the backend console for CP-SAT solver status per size")
    print("(OPTIMAL = proven optimal; FEASIBLE = hit the time limit).")


if __name__ == "__main__":
    main()