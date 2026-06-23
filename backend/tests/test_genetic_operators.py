"""Tests for GA selection, crossover and mutation operators."""

import random

from engine.graph_builder import build_flight_connection_graph
from engine.genetic_operators import tournament_select, crossover, mutate
from engine.solution import evaluate_solution
from factories import make_aircraft, dt


def test_tournament_returns_best_when_whole_population_competes():
    pop = [{"a": 1}, {"a": 2}, {"a": 3}]
    scores = [0.1, 0.9, 0.4]
    random.seed(0)
    winner = tournament_select(pop, scores, tournament_size=len(pop))
    assert winner == {"a": 2}  # highest score
    # Returns a copy, not the same object (so mutation can't corrupt the pool).
    assert winner is not pop[1]


def test_crossover_child_is_feasible(chain_flights, flights_by_id, two_aircraft):
    g = build_flight_connection_graph(chain_flights)
    parent_a = {"F1": "TC-AAA", "F2": "TC-AAA", "F3": "TC-AAA", "F4": "TC-AAA"}
    parent_b = {"F1": "TC-AAA", "F2": "TC-AAA", "F3": "TC-BBB", "F4": "TC-BBB"}
    random.seed(1)
    child = crossover(parent_a, parent_b, g, flights_by_id)
    assert evaluate_solution(child, flights_by_id, g).is_feasible is True


def test_crossover_only_uses_known_flights(chain_flights, flights_by_id, two_aircraft):
    g = build_flight_connection_graph(chain_flights)
    parent_a = {"F1": "TC-AAA", "F2": "TC-AAA", "F3": "TC-AAA", "F4": "TC-AAA"}
    parent_b = {"F1": "TC-BBB", "F2": "TC-BBB", "F3": "TC-BBB", "F4": "TC-BBB"}
    random.seed(2)
    child = crossover(parent_a, parent_b, g, flights_by_id)
    assert set(child.keys()) == set(flights_by_id.keys())


def test_mutation_never_assigns_an_unflyable_aircraft(chain_flights, flights_by_id):
    g = build_flight_connection_graph(chain_flights)
    usable = make_aircraft("OK", base="A", available_from=dt(0))
    late = make_aircraft("LATE", base="A", available_from=dt(5, 0, day=24))
    sol = {fid: None for fid in flights_by_id}
    random.seed(11)
    # Force a mutation attempt every call; LATE must never pick up a flight.
    for _ in range(200):
        sol = mutate(sol, g, flights_by_id, [usable, late], mutation_rate=1.0)
    assert "LATE" not in sol.values()


def test_mutation_keeps_solution_feasible(chain_flights, flights_by_id, two_aircraft):
    g = build_flight_connection_graph(chain_flights)
    sol = {fid: None for fid in flights_by_id}
    random.seed(99)
    for _ in range(200):
        sol = mutate(sol, g, flights_by_id, two_aircraft, mutation_rate=1.0)
        assert evaluate_solution(sol, flights_by_id, g).is_feasible is True
