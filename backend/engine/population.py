"""
Initial population generation for the genetic algorithm.

Strategy: greedy random construction guided by the Flight Connection Graph.
For each aircraft, we build a feasible rotation by:
  1. Picking a random "starting flight" (one whose origin matches the
     aircraft's base, or any flight if no match exists)
  2. Following random outgoing edges in the FCG to extend the rotation
  3. Stopping when no feasible next flight is available or all flights
     are already assigned

This produces feasible-by-construction solutions, which gives the GA
a much better starting point than pure random assignment.

Reproducibility note
--------------------
Candidate lists are sorted into a canonical (departure, flight_id) order
before the weighted random pick. The pick is order-sensitive
(random.choices maps a single RNG draw onto a list index), so without a
canonical order the GA's output would depend on the order edges happen to be
stored in the connection graph. Sorting makes a given seed fully reproducible
and independent of how the FCG was built (naive O(n^2) vs bucketed builder).
"""

import random
from typing import Optional

from engine.solution import aircraft_can_fly


def _sorted_candidates(candidate_ids, flights_by_id):
    """
    Returns candidate flight ids in a canonical (departure, flight_id) order.

    This is purely for determinism: the weighted pick downstream is sensitive
    to list order, so a stable, build-independent ordering keeps the GA
    reproducible across runs and across different graph builders.
    """
    return sorted(
        candidate_ids,
        key=lambda fid: (flights_by_id[fid].scheduled_departure, fid),
    )


def build_random_solution(
    aircraft_list: list,
    flights_by_id: dict,
    graph,
    aircraft_starts: dict = None,
) -> dict:
    """
    Constructs a single feasible-by-construction solution.

    Each aircraft flies one continuous rotation. At each step we look
    ahead one move: candidates with more onward connections are preferred
    (weighted random choice), reducing the chance of dead-ending early.
    This is a classic best-first / lookahead heuristic for constructive
    search; it raises average chain length without sacrificing diversity.

    Parameters:
        aircraft_list: list of Aircraft ORM objects
        flights_by_id: dict mapping flight_id -> Flight ORM object
        graph: the Flight Connection Graph (networkx DiGraph)

    Returns:
        dict mapping flight_id -> tail_number (or None)
    """
    assigned_flights: set[str] = set()
    solution: dict[str, Optional[str]] = {fid: None for fid in flights_by_id}

    aircraft_order = list(aircraft_list)
    random.shuffle(aircraft_order)

    for aircraft in aircraft_order:
        tail = aircraft.tail_number
        # This aircraft's availability / maintenance window. Only flights it can
        # legally operate are eligible for its rotation.
        caps_entry = (aircraft.available_from, aircraft.maintenance_due)
        # Enforced start airport (e.g. where the aircraft stands after its locked
        # past legs). When set, the rotation MUST begin there with no fallback;
        # when None, the base airport is just a soft preference as before.
        start_airport = aircraft_starts.get(tail) if aircraft_starts else None
        required_origin = (
            start_airport if start_airport is not None else aircraft.base_airport
        )

        # --- Pick a starting flight ---
        # Prefer flights departing the required origin with the most onward
        # connections. Candidate lists are sorted into a canonical order first
        # so the weighted pick is reproducible regardless of graph build order.
        base_candidates = _sorted_candidates(
            [
                fid for fid, f in flights_by_id.items()
                if fid not in assigned_flights and f.origin == required_origin
                and aircraft_can_fly(caps_entry, f)
            ],
            flights_by_id,
        )
        if base_candidates:
            current_fid = _weighted_pick_by_outdegree(base_candidates, graph)
        elif start_airport is not None:
            # Start position is enforced: the aircraft cannot begin a rotation
            # anywhere other than where it is, so it flies nothing this build.
            continue
        else:
            available = _sorted_candidates(
                [
                    fid for fid in flights_by_id
                    if fid not in assigned_flights
                    and aircraft_can_fly(caps_entry, flights_by_id[fid])
                ],
                flights_by_id,
            )
            if not available:
                # Nothing left that THIS aircraft may fly; another aircraft may
                # still be able to, so move on rather than ending construction.
                continue
            current_fid = _weighted_pick_by_outdegree(available, graph)

        # --- Extend the rotation, preferring high-connectivity successors ---
        while current_fid is not None:
            solution[current_fid] = tail
            assigned_flights.add(current_fid)

            next_candidates = _sorted_candidates(
                [
                    nxt for nxt in graph.successors(current_fid)
                    if nxt not in assigned_flights
                    and aircraft_can_fly(caps_entry, flights_by_id[nxt])
                ],
                flights_by_id,
            )
            if not next_candidates:
                current_fid = None
            else:
                current_fid = _weighted_pick_by_outdegree(next_candidates, graph)

    return solution


def _weighted_pick_by_outdegree(candidates, graph):
    """
    Picks one candidate flight, weighted by its onward connectivity.

    A flight with more outgoing edges in the FCG is more likely to be
    chosen, because continuing the rotation through it is less likely
    to dead-end soon. A small constant (+1) is added so that even
    dead-end flights have a nonzero chance, preserving diversity.

    `candidates` is expected to already be in a canonical order (see
    _sorted_candidates) so the weighted draw is reproducible.
    """
    weights = [graph.out_degree(fid) + 1 for fid in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def build_initial_population(
    population_size: int,
    aircraft_list: list,
    flights_by_id: dict,
    graph,
    seed: Optional[int] = None,
    aircraft_starts: dict = None,
) -> list[dict]:
    """
    Builds an initial population of feasible solutions for the GA.

    Parameters:
        population_size: number of solutions to generate
        aircraft_list: list of Aircraft ORM objects
        flights_by_id: dict mapping flight_id -> Flight ORM object
        graph: the Flight Connection Graph
        seed: optional random seed for reproducibility

    Returns:
        list of solution dicts
    """
    if seed is not None:
        random.seed(seed)

    population = []
    for _ in range(population_size):
        solution = build_random_solution(
            aircraft_list, flights_by_id, graph, aircraft_starts
        )
        population.append(solution)

    return population