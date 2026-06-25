"""
Solution representation and fitness evaluation for the aircraft
rotation problem.

A solution (chromosome) is a dict mapping each flight_id to either:
  - a tail_number (the aircraft assigned to that flight), or
  - None (the flight is not assigned to any aircraft)

A solution is "feasible" if no aircraft is double-booked and every
consecutive pair of flights for the same aircraft is connectable
(i.e. there is an edge in the Flight Connection Graph between them).

Fitness design (lexicographic — aligned with the CP-SAT solver):
    The objective is a strict priority order, NOT a weighted blend of
    coverage against efficiency:
        1. feasibility  (no broken FCG chain / unavailable aircraft / wrong start)
        2. coverage     (assign as many flights as possible — a published
                         schedule must be flown; this is a hard priority, never
                         traded away for efficiency)
        3. efficiency   (only AMONG equal-coverage solutions: low average idle
                         and fuel per assigned flight)

    This mirrors how the CP-SAT solver already behaves (coverage reward
    dominates its objective), so the genetic algorithm and CP-SAT optimise the
    SAME preference order — a GA-vs-CP-SAT comparison then reflects only the
    search method, not a different objective. The user's idle/fuel weights tune
    the tie-break in step 3; the coverage weight is intentionally NOT a lever
    here, because coverage is a constraint rather than a tradeable objective.

    Idle and fuel are still normalized PER ASSIGNED FLIGHT (not as totals) so
    the efficiency tie-break cannot be gamed by assigning very few flights.
"""

from dataclasses import dataclass
from typing import Optional

from engine.cost_model import flight_fuel_kg, idle_fuel_kg


# ---------------------------------------------------------------------------
# Aircraft availability / maintenance capability
# ---------------------------------------------------------------------------
# An aircraft cannot fly a flight that departs before it becomes available, nor
# one that operates on or after its next scheduled maintenance. These are
# aircraft-specific constraints, so they cannot live in the (aircraft-agnostic)
# Flight Connection Graph; instead they are checked wherever a flight is bound
# to a specific tail. The single rule lives here so every caller (fitness,
# population seeding, mutation, baseline) stays consistent.

def build_aircraft_caps(aircraft_list) -> dict:
    """
    Build a {tail_number: (available_from, maintenance_due)} capability map
    from a list of Aircraft ORM objects. Computed once and reused so the hot
    fitness loop does not re-read ORM attributes on every evaluation.
    """
    return {
        a.tail_number: (a.available_from, a.maintenance_due)
        for a in aircraft_list
    }


def aircraft_can_fly(caps_entry, flight) -> bool:
    """
    True if the aircraft described by `caps_entry` (an (available_from,
    maintenance_due) tuple) may operate `flight`.

    Rules:
      - available_from: the flight must depart at or after the aircraft is
        available (flight.scheduled_departure >= available_from).
      - maintenance_due: the flight must finish before the maintenance day
        (flight.scheduled_arrival.date() < maintenance_due). A flight that
        arrives on or after the maintenance date is rejected, because the
        aircraft is expected to be in the hangar that day.

    A None bound means "no constraint".
    """
    available_from, maintenance_due = caps_entry
    if available_from is not None and flight.scheduled_departure < available_from:
        return False
    if maintenance_due is not None and flight.scheduled_arrival.date() >= maintenance_due:
        return False
    return True


@dataclass
class FitnessBreakdown:
    """Detailed components of a fitness evaluation (useful for reporting)."""
    fitness: float           # combined weighted score (higher is better)
    coverage: float          # fraction of flights assigned (0.0 to 1.0)
    assigned_count: int      # number of flights assigned
    total_flights: int       # total flights in the problem
    total_idle_minutes: int  # sum of idle time between consecutive flights
    total_fuel_kg: float     # sum of flight fuel + APU fuel
    is_feasible: bool        # True if no constraint is violated
    ron_nights: int = 0      # NEW: overnight (remain-over-night) stops


# Default objective weights (must sum to 1.0).
# Coverage weighted highest because covering more flights is the
# primary business goal; idle and fuel are secondary efficiency goals.
DEFAULT_WEIGHTS = {
    "coverage": 0.50,
    "idle": 0.25,
    "fuel": 0.25,
}

# Per-flight normalization references.
# These are realistic averages for B737-800 domestic Turkish operations
# and put idle/fuel penalties on the same scale as coverage (0..~1).
IDLE_PER_FLIGHT_REFERENCE = 90.0      # 90 min idle per flight is "average"
FUEL_PER_FLIGHT_REFERENCE = 2500.0    # 2500 kg per flight is "average"


def evaluate_solution(
    solution: dict,
    flights_by_id: dict,
    graph,
    weights: Optional[dict] = None,
    aircraft_caps: Optional[dict] = None,
    aircraft_starts: Optional[dict] = None,
) -> FitnessBreakdown:
    """
    Computes the fitness of a candidate solution.

    Uses a lexicographic score (see the module docstring):
        fitness = assigned_count + efficiency        (feasible)
        fitness = assigned_count + efficiency - (total_flights + 2)  (infeasible)

    The integer part is the number of covered flights and the fractional part
    (0..1) is the efficiency tie-break, so any extra covered flight outranks any
    efficiency gain (cover-first, exactly like CP-SAT), and any feasible solution
    outranks any infeasible one. This makes it impossible to "cheat" by assigning
    few flights: fewer covered flights always means a strictly lower score.

    Parameters:
        solution: dict mapping flight_id -> tail_number (or None)
        flights_by_id: dict mapping flight_id -> Flight ORM object
        graph: the Flight Connection Graph (networkx DiGraph)
        weights: dict with keys 'coverage', 'idle', 'fuel'. Used to weight
                 the efficiency components. Defaults to DEFAULT_WEIGHTS.
        aircraft_caps: optional {tail: (available_from, maintenance_due)} map
                 (see build_aircraft_caps). When provided, a rotation that
                 assigns a flight to an aircraft that cannot legally operate it
                 (departs before availability, or operates on/after maintenance)
                 is marked infeasible. When None, no availability check is done.
        aircraft_starts: optional {tail: iata_code} map giving the airport each
                 aircraft is at when the plan starts (e.g. where it stands after
                 its locked past legs). When provided, a rotation whose FIRST
                 leg does not depart from that airport is infeasible: an aircraft
                 cannot teleport to begin a flight elsewhere. When None, no
                 start-position check is done.

    Returns:
        A FitnessBreakdown describing the solution's quality.
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS

    total_flights = len(flights_by_id)

    # Group assigned flights by aircraft
    by_aircraft: dict[str, list] = {}
    for flight_id, tail in solution.items():
        if tail is None:
            continue
        by_aircraft.setdefault(tail, []).append(flight_id)
    for tail, ids in by_aircraft.items():
        ids.sort(key=lambda fid: flights_by_id[fid].scheduled_departure)

    # Walk every rotation, accumulating metrics
    assigned_count = sum(1 for t in solution.values() if t is not None)
    coverage = assigned_count / total_flights if total_flights > 0 else 0.0

    total_idle_minutes = 0
    ron_nights = 0
    total_fuel = 0.0
    is_feasible = True

    for tail, flight_ids in by_aircraft.items():
        caps_entry = aircraft_caps.get(tail) if aircraft_caps else None
        start_airport = aircraft_starts.get(tail) if aircraft_starts else None
        for i, fid in enumerate(flight_ids):
            flight = flights_by_id[fid]
            # Aircraft availability / maintenance: a rotation that puts a flight
            # on a tail that cannot legally operate it is infeasible.
            if caps_entry is not None and not aircraft_can_fly(caps_entry, flight):
                is_feasible = False
            # Start position: the aircraft's first leg must depart from where it
            # actually is; it cannot teleport to start a rotation elsewhere.
            if i == 0 and start_airport is not None and flight.origin != start_airport:
                is_feasible = False
            total_fuel += flight_fuel_kg(flight.distance_km)
            if i == 0:
                continue
            prev_fid = flight_ids[i - 1]
            if not graph.has_edge(prev_fid, fid):
                is_feasible = False
                continue
            edge = graph.edges[prev_fid, fid]
            idle = edge["idle_minutes"]
            total_idle_minutes += idle
            total_fuel += idle_fuel_kg(idle)
            if edge.get("is_overnight"):
                ron_nights += 1

    # --- Efficiency: 0..1 score combining idle and fuel quality ---
    # Lower idle/fuel per flight -> higher efficiency.
    if assigned_count > 0:
        avg_idle = total_idle_minutes / assigned_count
        avg_fuel = total_fuel / assigned_count
    else:
        avg_idle = IDLE_PER_FLIGHT_REFERENCE * 2
        avg_fuel = FUEL_PER_FLIGHT_REFERENCE * 2

    # Each component: 1.0 means "as good as reference", 0.0 means "twice as bad"
    idle_score = max(0.0, 1.0 - avg_idle / (IDLE_PER_FLIGHT_REFERENCE * 2))
    fuel_score = max(0.0, 1.0 - avg_fuel / (FUEL_PER_FLIGHT_REFERENCE * 2))

    # Weighted average of the two efficiency components
    idle_w = weights["idle"]
    fuel_w = weights["fuel"]
    if idle_w + fuel_w > 0:
        efficiency = (idle_w * idle_score + fuel_w * fuel_score) / (idle_w + fuel_w)
    else:
        efficiency = 1.0

    # --- Lexicographic combination: feasibility > coverage > efficiency ---
    # Coverage is the PRIMARY goal and is never traded away for efficiency, so
    # the GA covers as many flights as it can first and only then minimises idle
    # and fuel — the same preference order the CP-SAT solver enforces. Encoded as
    # one score so the GA's max-fitness machinery is unchanged: the integer part
    # is the covered-flight count and the fractional part (0..1) is the
    # efficiency, so any extra covered flight outranks any efficiency gain.
    # Infeasible solutions are pushed below every feasible one (a rotation with a
    # broken FCG chain, an unavailable aircraft, or the wrong start airport is
    # invalid) so the search repairs feasibility first.
    fitness = assigned_count + efficiency
    if not is_feasible:
        fitness -= (total_flights + 2)

    return FitnessBreakdown(
        fitness=fitness,
        coverage=coverage,
        assigned_count=assigned_count,
        total_flights=total_flights,
        total_idle_minutes=total_idle_minutes,
        total_fuel_kg=total_fuel,
        is_feasible=is_feasible,
        ron_nights=ron_nights,
    )