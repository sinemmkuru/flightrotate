"""
Capacity planning (Lever A): how much fleet, and WHERE, to cover every flight.

When the optimizer leaves sold flights uncovered, the operational answer is not
"cancel" but "add capacity" — standby aircraft or an ACMI (wet-lease). This
analysis quantifies that decision: how many extra aircraft, at which airports,
turn the uncovered flights into a fully flyable plan, and the estimated cost.

Method (bounded — two solves, no iteration):
  1. Solve the schedule with the real fleet (each aircraft pinned to its base)
     to find the uncovered flights.
  2. Add one VIRTUAL (leased) aircraft at the origin of each uncovered flight,
     available before the schedule starts. This guarantees full coverage is
     reachable; the solver then uses only the aircraft it actually needs.
  3. Count how many rotations start at each airport in that full-coverage plan.
     An airport that launches more rotations than it has real aircraft needs the
     difference as leased capacity -> the recommendation, by airport, with cost.

Read-only: it never mutates the fleet or the database.
"""
from collections import Counter
from datetime import timedelta
from types import SimpleNamespace

from engine.graph_builder import build_flight_connection_graph
from engine.cp_sat_solver import run_cp_sat

# Representative all-in ACMI (wet-lease) day rate for a narrowbody, used only to
# put a price on the recommendation. A rough planning figure, not a quote.
LEASE_COST_USD_PER_DAY = 25000.0


def _starts(aircraft_list):
    return {a.tail_number: a.base_airport for a in aircraft_list}


def _chains_by_start(solution, flights_by_id):
    """Count rotations (chains) by the airport their first leg departs from."""
    by_tail = {}
    for fid, tail in solution.items():
        if tail is not None:
            by_tail.setdefault(tail, []).append(fid)
    counts = Counter()
    for ids in by_tail.values():
        ids.sort(key=lambda x: flights_by_id[x].scheduled_departure)
        counts[flights_by_id[ids[0]].origin] += 1
    return counts


def suggest_capacity(flights, aircraft_list, airport_turnarounds=None,
                     time_limit_seconds=15):
    """
    Return a capacity recommendation dict (see module docstring). `flights` and
    `aircraft_list` are live ORM objects; they are only read.
    """
    fbi = {f.flight_id: f for f in flights}
    graph = build_flight_connection_graph(flights, airport_turnarounds=airport_turnarounds)
    existing = Counter(a.base_airport for a in aircraft_list)

    # 1. Current plan with the real fleet.
    cur = run_cp_sat(
        flights, aircraft_list, graph,
        aircraft_starts=_starts(aircraft_list),
        time_limit_seconds=time_limit_seconds,
    )
    uncovered = [fid for fid, t in cur.best_solution.items() if t is None]
    current = {
        "coverage": cur.best_fitness.coverage,
        "aircraft": len(aircraft_list),
        "assigned": cur.best_fitness.assigned_count,
        "total": cur.best_fitness.total_flights,
        "uncovered": len(uncovered),
    }

    if not uncovered:
        return {
            "available": True,
            "full_coverage": True,
            "current": current,
            "add_aircraft": 0,
            "by_airport": {},
            "estimated_daily_cost_usd": 0.0,
            "lease_cost_per_aircraft_usd": LEASE_COST_USD_PER_DAY,
        }

    # 2. Augment with one leased aircraft per uncovered flight, at its origin.
    avail = min(f.scheduled_departure for f in flights) - timedelta(hours=1)
    virtual = [
        SimpleNamespace(
            tail_number=f"LEASE{i:03d}",
            aircraft_type="B737-800",
            base_airport=fbi[fid].origin,
            available_from=avail,
            maintenance_due=None,
            status="active",
        )
        for i, fid in enumerate(uncovered)
    ]
    aug_list = list(aircraft_list) + virtual
    aug = run_cp_sat(
        flights, aug_list, graph,
        aircraft_starts=_starts(aug_list),
        time_limit_seconds=time_limit_seconds,
    )

    # 3. Extra aircraft needed per airport = rotations starting there beyond the
    #    real aircraft already based there.
    chains = _chains_by_start(aug.best_solution, fbi)
    by_airport = {
        ap: chains[ap] - existing.get(ap, 0)
        for ap in chains
        if chains[ap] - existing.get(ap, 0) > 0
    }
    add_total = sum(by_airport.values())

    return {
        "available": True,
        "full_coverage": False,
        "current": current,
        "suggested": {
            "coverage": aug.best_fitness.coverage,
            "assigned": aug.best_fitness.assigned_count,
            "aircraft": len(aircraft_list) + add_total,
        },
        "add_aircraft": add_total,
        "by_airport": dict(sorted(by_airport.items(), key=lambda kv: -kv[1])),
        "estimated_daily_cost_usd": add_total * LEASE_COST_USD_PER_DAY,
        "lease_cost_per_aircraft_usd": LEASE_COST_USD_PER_DAY,
    }
