"""Tests for the genetic algorithm driver."""

from engine.graph_builder import build_flight_connection_graph
from engine.genetic_algorithm import run_genetic_algorithm
from factories import make_aircraft, dt

FAST = {
    "population_size": 30,
    "generations": 25,
    "tournament_size": 3,
    "elitism_count": 3,
    "mutation_rate": 0.3,
}
W = {"coverage": 0.5, "idle": 0.25, "fuel": 0.25}


def test_returns_result_with_convergence_history(chain_flights, one_aircraft):
    g = build_flight_connection_graph(chain_flights)
    res = run_genetic_algorithm(chain_flights, one_aircraft, g, W, FAST, seed=1)
    assert res.best_solution is not None
    assert res.best_fitness is not None
    assert len(res.convergence) == FAST["generations"]
    assert len(res.avg_per_generation) == FAST["generations"]
    assert res.elapsed_seconds >= 0


def test_best_solution_is_feasible(chain_flights, one_aircraft):
    g = build_flight_connection_graph(chain_flights)
    res = run_genetic_algorithm(chain_flights, one_aircraft, g, W, FAST, seed=1)
    assert res.best_fitness.is_feasible is True


def test_same_seed_is_reproducible(chain_flights, two_aircraft):
    g = build_flight_connection_graph(chain_flights)
    a = run_genetic_algorithm(chain_flights, two_aircraft, g, W, FAST, seed=42)
    b = run_genetic_algorithm(chain_flights, two_aircraft, g, W, FAST, seed=42)
    assert a.best_fitness.fitness == b.best_fitness.fitness
    assert a.best_solution == b.best_solution


def test_finds_full_coverage_on_easy_instance(chain_flights, one_aircraft):
    g = build_flight_connection_graph(chain_flights)
    res = run_genetic_algorithm(chain_flights, one_aircraft, g, W, FAST, seed=4)
    assert res.best_fitness.coverage == 1.0


def test_unavailable_aircraft_never_used_end_to_end(chain_flights):
    g = build_flight_connection_graph(chain_flights)
    usable = make_aircraft("OK", base="A", available_from=dt(0))
    late = make_aircraft("LATE", base="A", available_from=dt(5, 0, day=24))
    res = run_genetic_algorithm(chain_flights, [usable, late], g, W, FAST, seed=2)
    assert "LATE" not in res.best_solution.values()
    assert res.best_fitness.is_feasible is True
