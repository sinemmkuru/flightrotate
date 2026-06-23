"""
Naive greedy baseline for the aircraft rotation problem.

Purpose
-------
Provide a deterministic, non-optimized reference assignment so the
optimizer's contribution can be quantified ("% improvement vs naive").
This is the academic control: without a baseline, "coverage 62%" means
nothing; against a naive baseline of 45% it becomes a measurable gain.

The naive heuristic mimics a dispatcher with no optimization tooling:
process flights in departure order (first-come-first-served) and assign
each flight to the FIRST aircraft that can legally fly it -- extending an
aircraft whose last flight connects in the Flight Connection Graph,
otherwise starting the next idle aircraft. No idle/fuel minimization, no
look-ahead, no backtracking. It is intentionally simple and greedy.

Fairness
--------
KPIs are computed with the SAME engine.solution.evaluate_solution used by
the genetic algorithm and the CP-SAT solver, and fuel cost with the SAME
engine.cost_model.fuel_cost_usd. Only the assignment STRATEGY differs, not
the cost model -- so the comparison is strictly apples-to-apples.

The baseline is deterministic (fixed flight order, fixed aircraft order),
so it is perfectly reproducible for the thesis.
"""
from engine.graph_builder import build_flight_connection_graph
from engine.solution import evaluate_solution, build_aircraft_caps, aircraft_can_fly
from engine.cost_model import fuel_cost_usd


def greedy_baseline(flights, aircraft_list, graph) -> dict:
    """
    First-come-first-served greedy assignment.

    Parameters
    ----------
    flights : list[Flight]            ORM objects (status scheduled, not deleted)
    aircraft_list : list[Aircraft]    ORM objects (status active, not deleted)
    graph : networkx.DiGraph          the Flight Connection Graph (FCG)

    Returns
    -------
    dict: flight_id -> tail_number | None  (None = left unassigned)
    """
    ordered = sorted(flights, key=lambda f: f.scheduled_departure)
    tails = [a.tail_number for a in aircraft_list]
    # Availability / maintenance window per tail; the naive dispatcher still may
    # not assign a flight to an aircraft that cannot legally operate it.
    caps = build_aircraft_caps(aircraft_list)

    # Last flight currently flown by each aircraft (None = still on the ground).
    last_flight = {t: None for t in tails}
    solution = {f.flight_id: None for f in flights}

    for f in ordered:
        fid = f.flight_id
        chosen = None

        # 1) Extend the FIRST aircraft whose last flight connects to this one
        #    AND that may legally operate it. (Naive: first feasible, NOT the
        #    tightest turnaround.)
        for t in tails:
            lf = last_flight[t]
            if lf is not None and graph.has_edge(lf, fid) and aircraft_can_fly(caps[t], f):
                chosen = t
                break

        # 2) Otherwise start the first idle aircraft that may operate it.
        if chosen is None:
            for t in tails:
                if last_flight[t] is None and aircraft_can_fly(caps[t], f):
                    chosen = t
                    break

        if chosen is not None:
            solution[fid] = chosen
            last_flight[chosen] = fid
        # else: no aircraft can legally take this flight -> stays unassigned

    return solution


def compute_baseline_kpis(flights, aircraft_list, airport_turnarounds=None) -> dict:
    """
    Build the FCG, run the greedy baseline, and evaluate it with the same
    evaluator the optimizer uses. Returns a KPI dict ready to serialize.

    airport_turnarounds: optional {iata_code: min_turnaround_min} passed through
    to the graph builder so the baseline respects the same per-airport
    turnarounds as the optimizer (kept None-safe for script callers).
    """
    flights_by_id = {f.flight_id: f for f in flights}
    graph = build_flight_connection_graph(
        flights, airport_turnarounds=airport_turnarounds
    )
    solution = greedy_baseline(flights, aircraft_list, graph)
    caps = build_aircraft_caps(aircraft_list)
    b = evaluate_solution(solution, flights_by_id, graph, aircraft_caps=caps)

    return {
        "algorithm": "greedy_baseline",
        "coverage": b.coverage,                 # 0.0 - 1.0
        "assigned_flights": b.assigned_count,
        "total_flights": b.total_flights,
        "idle_minutes": b.total_idle_minutes,
        "fuel_kg": b.total_fuel_kg,
        "fuel_cost_usd": fuel_cost_usd(b.total_fuel_kg),
    }