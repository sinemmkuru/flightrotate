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
"""

import random
from typing import Optional


def build_random_solution(
    aircraft_list: list,
    flights_by_id: dict,
    graph,
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

        # --- Pick a starting flight ---
        # Prefer base-airport flights with the most onward connections
        base_candidates = [
            fid for fid, f in flights_by_id.items()
            if fid not in assigned_flights and f.origin == aircraft.base_airport
        ]
        if base_candidates:
            current_fid = _weighted_pick_by_outdegree(base_candidates, graph)
        else:
            available = [
                fid for fid in flights_by_id if fid not in assigned_flights
            ]
            if not available:
                break
            current_fid = _weighted_pick_by_outdegree(available, graph)

        # --- Extend the rotation, preferring high-connectivity successors ---
        while current_fid is not None:
            solution[current_fid] = tail
            assigned_flights.add(current_fid)

            next_candidates = [
                nxt for nxt in graph.successors(current_fid)
                if nxt not in assigned_flights
            ]
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
    """
    weights = [graph.out_degree(fid) + 1 for fid in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def build_initial_population(
    population_size: int,
    aircraft_list: list,
    flights_by_id: dict,
    graph,
    seed: Optional[int] = None,
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
        solution = build_random_solution(aircraft_list, flights_by_id, graph)
        population.append(solution)

    return population