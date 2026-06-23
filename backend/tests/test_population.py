"""Tests for the GA initial-population builder."""

from engine.graph_builder import build_flight_connection_graph
from engine.population import build_initial_population, build_random_solution
from engine.solution import evaluate_solution
from factories import make_aircraft, dt


def test_population_has_requested_size(chain_flights, flights_by_id, one_aircraft):
    g = build_flight_connection_graph(chain_flights)
    pop = build_initial_population(10, one_aircraft, flights_by_id, g, seed=1)
    assert len(pop) == 10


def test_every_individual_is_feasible_by_construction(
    chain_flights, flights_by_id, two_aircraft
):
    g = build_flight_connection_graph(chain_flights)
    pop = build_initial_population(15, two_aircraft, flights_by_id, g, seed=7)
    for sol in pop:
        assert evaluate_solution(sol, flights_by_id, g).is_feasible is True


def test_same_seed_reproduces_population(chain_flights, flights_by_id, two_aircraft):
    g = build_flight_connection_graph(chain_flights)
    a = build_initial_population(8, two_aircraft, flights_by_id, g, seed=42)
    b = build_initial_population(8, two_aircraft, flights_by_id, g, seed=42)
    assert a == b


def test_unavailable_aircraft_gets_no_flights(chain_flights, flights_by_id):
    g = build_flight_connection_graph(chain_flights)
    # One usable aircraft + one available only the next day (cannot fly any).
    usable = make_aircraft("OK", base="A", available_from=dt(0))
    late = make_aircraft("LATE", base="A", available_from=dt(5, 0, day=24))
    pop = build_initial_population(12, [usable, late], flights_by_id, g, seed=3)
    for sol in pop:
        assert "LATE" not in sol.values()


def test_single_aircraft_can_cover_the_whole_chain(
    chain_flights, flights_by_id, one_aircraft
):
    g = build_flight_connection_graph(chain_flights)
    # With a feasible 4-chain and one aircraft, a constructed rotation should be
    # able to reach full coverage at least once across the population.
    pop = build_initial_population(20, one_aircraft, flights_by_id, g, seed=5)
    best = max(evaluate_solution(s, flights_by_id, g).coverage for s in pop)
    assert best == 1.0
