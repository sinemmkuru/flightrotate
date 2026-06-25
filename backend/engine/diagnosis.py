"""
Decision-support diagnosis: WHY each scheduled flight ended up unassigned.

An assignment optimizer cannot "create" coverage. When a flight is left
unassigned it does not mean the solver failed — it means the fixed fleet
(count + position + availability) physically cannot fly it. The honest, useful
behaviour is therefore an OCC-style answer: instead of silently cancelling a
sold flight, report a reason code that points at the operational lever to
recover it.

Reasons (each maps to a real OCC lever):
  availability — no aircraft may legally operate the flight (it departs before
                 any aircraft is available, or the only eligible aircraft are in
                 maintenance / grounded). Lever: availability / maintenance.
  location     — the flight departs an airport where no eligible aircraft is
                 positioned AND no covered flight feeds an aircraft in, so there
                 is simply no aircraft there to fly it. Lever: base or position
                 (ferry) an aircraft at the origin.
  capacity     — the flight could be reached (an eligible aircraft starts at its
                 origin, or a covered flight lands there) but the fleet is
                 exhausted. Lever: add capacity (standby aircraft / wet-lease).

This is pure analysis over data already in hand (the solution, the connection
graph, and the fleet); it never mutates anything.
"""
from collections import Counter

from engine.solution import aircraft_can_fly

# Stable reason order (most-actionable / most-common first) and human labels.
REASON_ORDER = ["capacity", "location", "availability"]
REASON_LABEL = {
    "capacity": "Fleet exhausted (reachable, no aircraft free)",
    "location": "No aircraft positioned at the origin",
    "availability": "No eligible aircraft (availability / maintenance)",
}
# The operational lever that recovers each reason.
REASON_LEVER = {
    "capacity": "Add capacity (standby aircraft / wet-lease)",
    "location": "Base or position (ferry) an aircraft at the origin",
    "availability": "Resolve availability / maintenance",
}


def diagnose_unassigned(solution, flights_by_id, graph, aircraft_list,
                        aircraft_starts=None):
    """
    Classify every unassigned flight in `solution` (flight_id -> tail | None).

    Parameters mirror engine.solution.evaluate_solution: `aircraft_list` are the
    (effective) aircraft, and `aircraft_starts` maps tail -> the airport it
    stands at when the plan starts (defaults to each aircraft's base_airport).

    Returns a list of dicts (one per unassigned flight) with flight metadata, a
    `reason` code and its human `reason_label`, sorted by reason then departure.
    """
    starts = aircraft_starts or {}
    caps = {a.tail_number: (a.available_from, a.maintenance_due) for a in aircraft_list}

    rows = []
    for fid, tail in solution.items():
        if tail is not None:
            continue
        f = flights_by_id.get(fid)
        if f is None:
            continue

        eligible = [a for a in aircraft_list if aircraft_can_fly(caps[a.tail_number], f)]
        if not eligible:
            reason = "availability"
        else:
            # An eligible aircraft standing at this origin could start a rotation
            # here; a covered flight landing here could continue onto it. Either
            # way the flight is *reachable*, so being uncovered means the fleet
            # ran out (capacity). Otherwise no aircraft can ever get here
            # (location / positioning).
            starts_here = any(
                starts.get(a.tail_number, a.base_airport) == f.origin
                for a in eligible
            )
            covered_inbound = (
                graph.has_node(fid)
                and any(solution.get(p) is not None for p in graph.predecessors(fid))
            )
            reason = "capacity" if (starts_here or covered_inbound) else "location"

        rows.append({
            "flight_id": fid,
            "flight_number": getattr(f, "flight_number", fid),
            "origin": f.origin,
            "destination": f.destination,
            "route": f"{f.origin}->{f.destination}",
            "scheduled_departure": f.scheduled_departure.isoformat(),
            "reason": reason,
            "reason_label": REASON_LABEL[reason],
            "lever": REASON_LEVER[reason],
        })

    rows.sort(key=lambda r: (
        REASON_ORDER.index(r["reason"]) if r["reason"] in REASON_ORDER else 9,
        r["scheduled_departure"],
    ))
    return rows


def summarize_reasons(rows):
    """Roll up a diagnosis list into {total, by_reason} (reason -> count)."""
    counts = Counter(r["reason"] for r in rows)
    # Emit reasons in the canonical order so the UI is stable.
    by_reason = {r: counts[r] for r in REASON_ORDER if counts.get(r)}
    return {"total": len(rows), "by_reason": by_reason}
