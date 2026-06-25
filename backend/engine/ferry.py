"""
Repositioning / ferry recovery (Lever B): cover stranded flights by flying an
idle aircraft there EMPTY, at fuel cost.

Where Lever A (engine.capacity) adds aircraft, Lever B uses the ones you already
have better: an aircraft that is idle, or that finishes its rotation early, can
fly an empty positioning leg (a ferry) to an airport that has an uncovered
flight and operate it. This is a real OCC technique; the cost is the ferry fuel
(an empty leg earns no revenue), which is reported honestly. No commercial flight
is invented — there is no demand model, so the positioning leg flies empty.

Method (bounded, read-only — does not mutate anything):
  1. Solve the schedule with the real fleet (each aircraft pinned to its base).
  2. From that plan, work out where each aircraft ends up and when it is free
     (idle aircraft are free at their base; used aircraft are free after their
     last leg, at that leg's destination). Ferrying after a rotation never
     breaks the rotation — it is extra flying on top.
  3. Walk the uncovered flights in departure order; for each, pick the cheapest
     (nearest) available aircraft that can ferry to its origin in time, assign
     it, and move that aircraft's position/free-time forward so it can reposition
     again. Greedy and bounded by how many idle aircraft exist.

The result lists the ferry legs (aircraft, route, distance, fuel, the flight each
enables), the coverage lift, and the total empty-ferry overhead and cost.
"""
from datetime import timedelta

from engine.graph_builder import build_flight_connection_graph, DEFAULT_MIN_TURNAROUND
from engine.cp_sat_solver import run_cp_sat
from engine.solution import aircraft_can_fly
from engine.geo import haversine, estimate_flight_duration_minutes
from engine.cost_model import flight_fuel_kg, fuel_cost_usd


def _turn(airport_turnarounds, code):
    if airport_turnarounds:
        return airport_turnarounds.get(code, DEFAULT_MIN_TURNAROUND)
    return DEFAULT_MIN_TURNAROUND


def plan_ferries(flights, aircraft_list, airport_coords,
                 airport_turnarounds=None, time_limit_seconds=15):
    """
    Return a ferry-recovery plan (see module docstring). `airport_coords` maps
    iata_code -> (latitude, longitude). `flights` / `aircraft_list` are read-only.
    """
    fbi = {f.flight_id: f for f in flights}
    graph = build_flight_connection_graph(
        flights, airport_turnarounds=airport_turnarounds
    )
    starts = {a.tail_number: a.base_airport for a in aircraft_list}

    base = run_cp_sat(
        flights, aircraft_list, graph,
        aircraft_starts=starts, time_limit_seconds=time_limit_seconds,
    )
    base_sol = base.best_solution
    total = len(flights)
    base_assigned = sum(1 for t in base_sol.values() if t is not None)

    # Where each aircraft stands and when it is free after the base plan.
    by_tail = {}
    for fid, tail in base_sol.items():
        if tail is not None:
            by_tail.setdefault(tail, []).append(fid)
    avail = []
    for a in aircraft_list:
        legs = by_tail.get(a.tail_number)
        if legs:
            legs.sort(key=lambda x: fbi[x].scheduled_departure)
            last = fbi[legs[-1]]
            loc, free = last.destination, (
                last.scheduled_arrival + timedelta(minutes=_turn(airport_turnarounds, last.destination))
            )
        else:
            loc, free = a.base_airport, a.available_from
        avail.append({
            "tail": a.tail_number, "loc": loc, "free": free,
            "caps": (a.available_from, a.maintenance_due),
        })

    uncovered = sorted(
        (fid for fid, t in base_sol.items() if t is None),
        key=lambda x: fbi[x].scheduled_departure,
    )

    ferries = []
    recovered = 0
    unrecoverable = 0
    for fid in uncovered:
        f = fbi[fid]
        if f.origin not in airport_coords:
            unrecoverable += 1
            continue

        best = None
        for ac in avail:
            if ac["loc"] not in airport_coords:
                continue
            if not aircraft_can_fly(ac["caps"], f):
                continue
            dist = haversine(*airport_coords[ac["loc"]], *airport_coords[f.origin])
            dur = estimate_flight_duration_minutes(dist)
            ferry_dep = ac["free"]
            ferry_arr = ferry_dep + timedelta(minutes=dur)
            ready = ferry_arr + timedelta(minutes=_turn(airport_turnarounds, f.origin))
            if ready <= f.scheduled_departure and (best is None or dist < best["dist"]):
                best = {"ac": ac, "dist": dist, "dur": dur,
                        "dep": ferry_dep, "arr": ferry_arr}

        if best is None:
            unrecoverable += 1
            continue

        ac = best["ac"]
        dist = best["dist"]
        fuel = flight_fuel_kg(dist) if dist >= 1 else 0.0
        ferries.append({
            "tail": ac["tail"],
            "from": ac["loc"],
            "to": f.origin,
            "distance_km": round(dist),
            "fuel_kg": round(fuel, 1),
            "ferry_departure": best["dep"].isoformat(),
            "ferry_arrival": best["arr"].isoformat(),
            "enables_flight": f.flight_number,
            "enables_route": f"{f.origin}->{f.destination}",
        })
        recovered += 1
        # The aircraft now stands at the flight's destination, free after it.
        ac["loc"] = f.destination
        ac["free"] = f.scheduled_arrival + timedelta(
            minutes=_turn(airport_turnarounds, f.destination)
        )

    total_km = sum(fr["distance_km"] for fr in ferries)
    total_fuel = sum(fr["fuel_kg"] for fr in ferries)
    return {
        "available": True,
        "base_coverage": base.best_fitness.coverage,
        "ferry_coverage": (base_assigned + recovered) / total if total else 0.0,
        "recovered": recovered,
        "unrecoverable": unrecoverable,
        "ferries": ferries,
        "ferry_legs": len(ferries),
        "total_ferry_km": total_km,
        "total_ferry_fuel_kg": round(total_fuel, 1),
        "estimated_ferry_cost_usd": round(fuel_cost_usd(total_fuel), 2),
    }
