"""
Genetic algorithm operators: selection, crossover, and mutation.

These operators work on solution dicts (flight_id -> tail_number or None)
and use the Flight Connection Graph to keep all produced children feasible.

Design choices:
  - Tournament selection: pick K random individuals, return the best.
  - Aircraft-level uniform crossover: for each aircraft, randomly inherit
    its complete rotation from either parent. This preserves rotation-
    level feasibility (each inherited rotation was already feasible in
    its parent) while introducing diversity at the fleet level.
  - Two mutation operators (extend / swap) that respect FCG feasibility.

Determinism note:
  Any iteration over a Python set of strings is ordered by the strings'
  hashes, which are randomized per process (PYTHONHASHSEED). Such orders are
  therefore turned into a canonical order with sorted(...) before they can
  influence a result, so a fixed seed reproduces the same run across
  processes/machines without relying on an environment variable.
"""

import random
from typing import Optional

from engine.solution import aircraft_can_fly


# ---------------------------------------------------------------------------
# SELECTION
# ---------------------------------------------------------------------------

def tournament_select(
    population: list[dict],
    fitness_scores: list[float],
    tournament_size: int = 3,
) -> dict:
    """
    Picks K random individuals from the population and returns the one
    with the highest fitness score.
    """
    if tournament_size > len(population):
        tournament_size = len(population)
    contender_indices = random.sample(range(len(population)), tournament_size)
    best_idx = max(contender_indices, key=lambda i: fitness_scores[i])
    return dict(population[best_idx])


# ---------------------------------------------------------------------------
# CROSSOVER
# ---------------------------------------------------------------------------

def crossover(
    parent_a: dict,
    parent_b: dict,
    graph,
    flights_by_id: dict,
) -> dict:
    """
    Aircraft-level uniform crossover.

    For each aircraft, flip a coin to decide which parent contributes
    that aircraft's complete rotation. Because each parent's rotation
    for a given aircraft was already feasible (the FCG was respected
    when it was built), the inherited rotation stays feasible in the child.

    Flight-level conflicts (same flight assigned to two aircraft in
    different parents) are resolved by random tie-breaking.

    Parameters:
        parent_a: first parent solution
        parent_b: second parent solution
        graph: the Flight Connection Graph (kept in signature for symmetry
               with mutation; this crossover does not need it directly)
        flights_by_id: dict mapping flight_id -> Flight ORM object

    Returns:
        A new feasible solution dict
    """
    # Group each parent's assignments by aircraft
    a_by_aircraft = _group_by_aircraft(parent_a)
    b_by_aircraft = _group_by_aircraft(parent_b)

    # Union of aircraft that appear in either parent
    all_tails = set(a_by_aircraft) | set(b_by_aircraft)

    # Build the child by choosing one parent per aircraft
    child: dict[str, Optional[str]] = {fid: None for fid in flights_by_id}
    used_flights: set[str] = set()

    # Process aircraft in random order so the same flight conflict is resolved
    # differently each call (preserves diversity). sorted() first gives a
    # canonical, hash-independent starting order, so the seeded shuffle below
    # produces the SAME permutation across processes (reproducible runs).
    aircraft_order = sorted(all_tails)
    random.shuffle(aircraft_order)

    for tail in aircraft_order:
        # Randomly pick which parent contributes this aircraft's rotation
        a_flights = a_by_aircraft.get(tail, [])
        b_flights = b_by_aircraft.get(tail, [])

        # Skip if neither parent has this aircraft used
        if not a_flights and not b_flights:
            continue

        # Coin flip; if one side is empty, take the other
        if a_flights and b_flights:
            source = a_flights if random.random() < 0.5 else b_flights
        else:
            source = a_flights or b_flights

        # Inherit only flights that are not already taken by another aircraft
        for fid in source:
            if fid not in used_flights:
                child[fid] = tail
                used_flights.add(fid)

    return child


def _group_by_aircraft(solution: dict) -> dict[str, list[str]]:
    """Helper: returns {tail_number: [flight_id, ...]} from a solution."""
    by_tail: dict[str, list[str]] = {}
    for fid, tail in solution.items():
        if tail is not None:
            by_tail.setdefault(tail, []).append(fid)
    return by_tail


# ---------------------------------------------------------------------------
# MUTATION
# ---------------------------------------------------------------------------

def mutate(
    solution: dict,
    graph,
    flights_by_id: dict,
    aircraft_list: list,
    mutation_rate: float = 0.15,
    aircraft_starts: dict = None,
) -> dict:
    """
    Applies a small random change to a solution.

    Two mutation moves chosen randomly:
      - "extend": pick an unassigned flight, try to attach it to any
        aircraft whose rotation can absorb it
      - "swap": pick an assigned flight, try to move it to a different
        aircraft

    Each candidate move is FCG-checked; infeasible moves are silently
    skipped. When aircraft_starts is given, an aircraft's first leg must depart
    from its start airport (see _is_assignment_feasible).
    """
    if random.random() > mutation_rate:
        return solution

    if random.random() < 0.6:
        # Extend is more valuable than swap for raising coverage,
        # so it gets a slightly higher chance.
        _try_extend(solution, graph, flights_by_id, aircraft_list, aircraft_starts)
    else:
        _try_swap(solution, graph, flights_by_id, aircraft_list, aircraft_starts)

    return solution


def _start_for(aircraft_starts, tail):
    return aircraft_starts.get(tail) if aircraft_starts else None


def _try_extend(solution, graph, flights_by_id, aircraft_list, aircraft_starts=None):
    """
    Try to assign one currently-unassigned flight to an aircraft.
    """
    unassigned = [fid for fid, t in solution.items() if t is None]
    if not unassigned:
        return
    target_fid = random.choice(unassigned)

    target_flight = flights_by_id[target_fid]
    candidates = list(aircraft_list)
    random.shuffle(candidates)
    for aircraft in candidates[:10]:  # try up to 10 aircraft
        # Skip aircraft that cannot legally operate this flight (availability /
        # maintenance) before paying for the FCG feasibility check.
        if not aircraft_can_fly(
            (aircraft.available_from, aircraft.maintenance_due), target_flight
        ):
            continue
        if _is_assignment_feasible(
            solution, target_fid, aircraft.tail_number, graph, flights_by_id,
            _start_for(aircraft_starts, aircraft.tail_number),
        ):
            solution[target_fid] = aircraft.tail_number
            return


def _try_swap(solution, graph, flights_by_id, aircraft_list, aircraft_starts=None):
    """
    Try to move one currently-assigned flight to a different aircraft.
    """
    assigned = [fid for fid, t in solution.items() if t is not None]
    if not assigned:
        return
    target_fid = random.choice(assigned)
    current_tail = solution[target_fid]

    target_flight = flights_by_id[target_fid]
    solution[target_fid] = None
    # Pulling a flight out of the MIDDLE of its old rotation can leave the two
    # halves no longer connectable (e.g. A->B->C becomes A,C with no A->C edge),
    # or strip away the leg that anchored the rotation to the aircraft's start
    # airport. If removing it breaks the source rotation, undo and bail.
    if not _rotation_feasible(
        solution, current_tail, graph, flights_by_id,
        _start_for(aircraft_starts, current_tail),
    ):
        solution[target_fid] = current_tail
        return
    candidates = [a for a in aircraft_list if a.tail_number != current_tail]
    random.shuffle(candidates)
    for aircraft in candidates[:10]:
        if not aircraft_can_fly(
            (aircraft.available_from, aircraft.maintenance_due), target_flight
        ):
            continue
        if _is_assignment_feasible(
            solution, target_fid, aircraft.tail_number, graph, flights_by_id,
            _start_for(aircraft_starts, aircraft.tail_number),
        ):
            solution[target_fid] = aircraft.tail_number
            return

    solution[target_fid] = current_tail  # restore


def _rotation_feasible(solution, tail, graph, flights_by_id, start_airport=None) -> bool:
    """
    True if the flights currently assigned to `tail` form a connectable chain:
    sorted by departure, every consecutive pair must have an FCG edge, and (when
    given) the first leg must depart from the aircraft's start airport. A
    rotation of fewer than two flights is trivially feasible apart from start.
    """
    seq = [fid for fid, t in solution.items() if t == tail]
    if not seq:
        return True
    seq.sort(key=lambda fid: flights_by_id[fid].scheduled_departure)
    if start_airport is not None and flights_by_id[seq[0]].origin != start_airport:
        return False
    return all(
        graph.has_edge(seq[i], seq[i + 1]) for i in range(len(seq) - 1)
    )


def _is_assignment_feasible(
    solution: dict,
    new_fid: str,
    tail: str,
    graph,
    flights_by_id: dict,
    start_airport: str = None,
) -> bool:
    """
    Checks whether assigning new_fid to the given aircraft keeps its rotation
    feasible: every consecutive pair has an FCG edge and, when start_airport is
    given, the rotation's first leg departs from it (an aircraft cannot teleport
    to begin elsewhere).
    """
    existing = [fid for fid, t in solution.items() if t == tail]
    if not existing:
        return start_airport is None or flights_by_id[new_fid].origin == start_airport
    new_seq = existing + [new_fid]
    new_seq.sort(key=lambda fid: flights_by_id[fid].scheduled_departure)
    # The new flight may become the earliest leg, so re-check the start airport.
    if start_airport is not None and flights_by_id[new_seq[0]].origin != start_airport:
        return False
    for i in range(len(new_seq) - 1):
        if not graph.has_edge(new_seq[i], new_seq[i + 1]):
            return False
    return True