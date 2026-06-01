"""
Solution representation and fitness evaluation for the aircraft
rotation problem.

A solution (chromosome) is a dict mapping each flight_id to either:
  - a tail_number (the aircraft assigned to that flight), or
  - None (the flight is not assigned to any aircraft)

A solution is "feasible" if no aircraft is double-booked and every
consecutive pair of flights for the same aircraft is connectable
(i.e. there is an edge in the Flight Connection Graph between them).

Fitness design:
    The objective is a weighted sum of three terms:
        + coverage  (fraction of flights assigned, 0..1)
        - idle      (average idle minutes per assigned flight, normalized)
        - fuel      (average fuel kg per assigned flight, normalized)

    Critical design choice: idle and fuel penalties are normalized
    PER ASSIGNED FLIGHT, not as totals. Otherwise the algorithm can
    "cheat" by assigning very few flights to minimize absolute idle
    and fuel costs - which technically maximizes fitness but gives
    a useless solution.
"""

from dataclasses import dataclass
from typing import Optional

from engine.cost_model import flight_fuel_kg, idle_fuel_kg


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
) -> FitnessBreakdown:
    """
    Computes the fitness of a candidate solution.

    Uses a multiplicative form:
        fitness = coverage * efficiency

    where efficiency rewards low average idle and low average fuel per
    assigned flight, normalized to 0..1. This makes it impossible to
    "cheat" by assigning few flights: low coverage forces low fitness
    regardless of efficiency.

    Parameters:
        solution: dict mapping flight_id -> tail_number (or None)
        flights_by_id: dict mapping flight_id -> Flight ORM object
        graph: the Flight Connection Graph (networkx DiGraph)
        weights: dict with keys 'coverage', 'idle', 'fuel'. Used to weight
                 the efficiency components. Defaults to DEFAULT_WEIGHTS.

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
    total_fuel = 0.0
    is_feasible = True

    for tail, flight_ids in by_aircraft.items():
        for i, fid in enumerate(flight_ids):
            flight = flights_by_id[fid]
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

    # --- Multiplicative combination ---
    # coverage_weight controls how much we emphasize coverage vs efficiency.
    # With coverage_weight=0.7, low coverage dominates: at 20% coverage even
    # perfect efficiency yields fitness ~0.34.
    coverage_weight = weights["coverage"] * 2  # scale to 0..1 emphasis
    coverage_weight = min(1.0, coverage_weight)

    fitness = (coverage ** coverage_weight) * efficiency

    if not is_feasible:
        fitness *= 0.1  # multiplicative penalty: nearly zero out the score

    return FitnessBreakdown(
        fitness=fitness,
        coverage=coverage,
        assigned_count=assigned_count,
        total_flights=total_flights,
        total_idle_minutes=total_idle_minutes,
        total_fuel_kg=total_fuel,
        is_feasible=is_feasible,
    )