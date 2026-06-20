"""
Disruption & recovery analysis for FlightRotate.

Simulates an operational disruption and RE-OPTIMIZES, then reports the impact:
how coverage / idle / fuel change and which flights had to be re-sequenced,
dropped, or were newly picked up. This answers the thesis question: "when the
day goes wrong, how well does the optimizer recover?"

v1 scope
--------
* ground_aircraft : an aircraft goes AOG (Aircraft On Ground) and is removed
                    from the available fleet.
* cancel          : a flight is removed from the schedule.

Both disruptions only FILTER the in-memory ORM lists -- no attribute is
mutated and nothing is written to the database, so the live schedule is never
touched. (Delay, which needs to shift a flight's times, is left for a
follow-up.)

Method
------
* "Before" and "After" are BOTH solved here with CP-SAT and identical
  settings, so the delta is caused purely by the disruption (not solver noise).
  Note: this "before" is a fresh CP-SAT optimum and may label aircraft
  differently from a stored genetic run -- that is expected and harmless.
* KPIs use the same evaluate_solution / fuel_cost_usd as the rest of the app.

Tail-label invariance
---------------------
All aircraft are interchangeable B737-800s and base_airport is only a soft
preference, so the physical tail a chain is labelled with carries no
operational meaning. A flight is therefore counted as "moved" ONLY if its
rotation context -- the flight immediately before and after it -- changes.
Pure tail relabelling (same chain, different label) is correctly reported as
"unchanged". This keeps the impact numbers honest.
"""
import time

from engine.graph_builder import build_flight_connection_graph
from engine.cp_sat_solver import run_cp_sat
from engine.cost_model import fuel_cost_usd


def _solve(flights, aircraft_list, weights):
    """Build the FCG and run CP-SAT; return (solution_dict, FitnessBreakdown)."""
    graph = build_flight_connection_graph(flights)
    result = run_cp_sat(
        flights=flights,
        aircraft_list=aircraft_list,
        graph=graph,
        weights=weights,
    )
    return result.best_solution, result.best_fitness


def _kpi(bd):
    return {
        "coverage": bd.coverage,
        "assigned_flights": bd.assigned_count,
        "total_flights": bd.total_flights,
        "idle_minutes": bd.total_idle_minutes,
        "fuel_kg": bd.total_fuel_kg,
        "fuel_cost_usd": fuel_cost_usd(bd.total_fuel_kg),
    }


def _apply(flights, aircraft_list, dtype, flight_id, tail_number):
    """Return (label, disrupted_flights, disrupted_aircraft). No mutation."""
    if dtype == "cancel":
        fmap = {f.flight_id: f for f in flights}
        if flight_id not in fmap:
            raise ValueError(f"Unknown flight_id: {flight_id}")
        label = f"Cancelled flight {fmap[flight_id].flight_number}"
        dis_flights = [f for f in flights if f.flight_id != flight_id]
        return label, dis_flights, list(aircraft_list)

    if dtype == "ground_aircraft":
        tails = {a.tail_number for a in aircraft_list}
        if tail_number not in tails:
            raise ValueError(f"Unknown tail_number: {tail_number}")
        label = f"Grounded aircraft {tail_number} (AOG)"
        dis_aircraft = [a for a in aircraft_list if a.tail_number != tail_number]
        return label, list(flights), dis_aircraft

    if dtype == "delay":
        raise ValueError("Delay disruption is not supported yet; use "
                         "'cancel' or 'ground_aircraft'.")

    raise ValueError(f"Unknown disruption type: {dtype}")


def _chain_neighbors(solution, fmap):
    """
    For a solution (flight_id -> tail | None), return two dicts mapping each
    assigned flight to its predecessor and successor flight within the same
    aircraft's rotation (ordered by departure). Tail labels are NOT used in
    the result -- only the flight-to-flight sequence, which is what is
    operationally meaningful.
    """
    by_tail = {}
    for fid, tail in solution.items():
        if tail is None:
            continue
        by_tail.setdefault(tail, []).append(fid)

    prev, nxt = {}, {}
    for ids in by_tail.values():
        ids.sort(key=lambda x: fmap[x].scheduled_departure)
        for i, fid in enumerate(ids):
            prev[fid] = ids[i - 1] if i > 0 else None
            nxt[fid] = ids[i + 1] if i < len(ids) - 1 else None
    return prev, nxt


def _fnum(fmap, fid):
    return fmap[fid].flight_number if fid in fmap else fid


def _impact(flights, before_sol, after_sol, dtype, flight_id):
    """
    Compare before/after assignments by ROTATION CONTEXT (predecessor and
    successor), not by tail label, so interchangeable-aircraft relabelling is
    not mistaken for a real operational move.
    """
    fmap = {f.flight_id: f for f in flights}
    b_prev, b_next = _chain_neighbors(before_sol, fmap)
    a_prev, a_next = _chain_neighbors(after_sol, fmap)

    affected = []
    dropped = moved = added = unchanged = 0

    for fid in after_sol.keys():           # flights that still exist after
        before_assigned = before_sol.get(fid) is not None
        after_assigned = after_sol.get(fid) is not None
        f = fmap.get(fid)
        route = f"{f.origin}->{f.destination}" if f else ""
        fnum = f.flight_number if f else fid

        if not after_assigned:
            if before_assigned:
                dropped += 1
                affected.append({"flight_id": fid, "flight_number": fnum,
                                 "route": route, "change": "dropped",
                                 "detail": "no longer covered"})
            else:
                unchanged += 1
            continue

        if not before_assigned:
            added += 1
            ap = a_prev.get(fid)
            detail = f"now after {_fnum(fmap, ap)}" if ap else "now starts a rotation"
            affected.append({"flight_id": fid, "flight_number": fnum,
                             "route": route, "change": "added", "detail": detail})
            continue

        # Both assigned -> compare rotation context (tail-label-invariant).
        same = (b_prev.get(fid) == a_prev.get(fid)
                and b_next.get(fid) == a_next.get(fid))
        if same:
            unchanged += 1
        else:
            moved += 1
            ap = a_prev.get(fid)
            detail = f"now after {_fnum(fmap, ap)}" if ap else "now starts a rotation"
            affected.append({"flight_id": fid, "flight_number": fnum,
                             "route": route, "change": "moved", "detail": detail})

    cancelled = 0
    if dtype == "cancel" and flight_id in fmap:
        cancelled = 1
        f = fmap[flight_id]
        affected.insert(0, {
            "flight_id": flight_id, "flight_number": f.flight_number,
            "route": f"{f.origin}->{f.destination}",
            "change": "cancelled", "detail": "removed from schedule",
        })

    order = {"cancelled": 0, "dropped": 1, "moved": 2, "added": 3}
    affected.sort(key=lambda x: order.get(x["change"], 9))

    return {
        "flights_cancelled": cancelled,
        "flights_dropped": dropped,
        "flights_moved": moved,
        "flights_added": added,
        "flights_unchanged": unchanged,
        "affected": affected,
    }


def _summary(label, before_bd, after_bd, impact):
    cov_b = before_bd.coverage * 100.0
    cov_a = after_bd.coverage * 100.0
    dpp = cov_a - cov_b

    parts = [f"{label}."]
    if impact["flights_cancelled"]:
        parts.append(f"{impact['flights_cancelled']} flight removed from the schedule.")
    if impact["flights_moved"]:
        parts.append(f"The optimizer re-sequenced {impact['flights_moved']} "
                     f"flight(s) into different rotations.")
    if impact["flights_dropped"]:
        parts.append(f"{impact['flights_dropped']} flight(s) could not be "
                     f"recovered and became uncovered.")
    if impact["flights_added"]:
        parts.append(f"{impact['flights_added']} previously-uncovered "
                     f"flight(s) were picked up.")
    if (not impact["flights_moved"] and not impact["flights_dropped"]
            and not impact["flights_added"] and not impact["flights_cancelled"]):
        parts.append("No rotations had to change.")

    if abs(dpp) < 0.05:
        cov_phrase = "Coverage held steady"
    elif dpp < 0:
        cov_phrase = f"Coverage dropped {abs(dpp):.1f} pp"
    else:
        cov_phrase = f"Coverage rose {abs(dpp):.1f} pp"
    parts.append(f"{cov_phrase} ({cov_b:.1f}% -> {cov_a:.1f}%).")
    return " ".join(parts)


def run_disruption(flights, aircraft_list, *, dtype,
                   flight_id=None, tail_number=None, weights=None):
    """
    Solve the original schedule, apply the disruption, re-solve, and return a
    before/after impact report. `flights` and `aircraft_list` are live ORM
    objects; they are only read and filtered, never mutated.
    """
    t0 = time.perf_counter()

    before_sol, before_bd = _solve(flights, aircraft_list, weights)
    label, dis_flights, dis_aircraft = _apply(
        flights, aircraft_list, dtype, flight_id, tail_number
    )
    after_sol, after_bd = _solve(dis_flights, dis_aircraft, weights)

    impact = _impact(flights, before_sol, after_sol, dtype, flight_id)
    summary = _summary(label, before_bd, after_bd, impact)

    return {
        "disruption": {
            "type": dtype, "label": label,
            "flight_id": flight_id, "tail_number": tail_number,
        },
        "algorithm": "cp_sat",
        "before": _kpi(before_bd),
        "after": _kpi(after_bd),
        "impact": impact,
        "summary": summary,
        "elapsed_seconds": round(time.perf_counter() - t0, 2),
    }