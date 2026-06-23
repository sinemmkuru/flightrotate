"""Tests for the naive greedy baseline."""

from engine.graph_builder import build_flight_connection_graph
from engine.baseline import greedy_baseline, compute_baseline_kpis
from engine.solution import evaluate_solution
from factories import make_aircraft, dt


def test_greedy_is_feasible(chain_flights, flights_by_id, one_aircraft):
    g = build_flight_connection_graph(chain_flights)
    sol = greedy_baseline(chain_flights, one_aircraft, g)
    assert evaluate_solution(sol, flights_by_id, g).is_feasible is True


def test_greedy_covers_the_full_chain_with_one_aircraft(
    chain_flights, flights_by_id, one_aircraft
):
    g = build_flight_connection_graph(chain_flights)
    sol = greedy_baseline(chain_flights, one_aircraft, g)
    assert all(t is not None for t in sol.values())


def test_greedy_is_deterministic(chain_flights, two_aircraft):
    g = build_flight_connection_graph(chain_flights)
    a = greedy_baseline(chain_flights, two_aircraft, g)
    b = greedy_baseline(chain_flights, two_aircraft, g)
    assert a == b


def test_greedy_respects_availability(chain_flights):
    g = build_flight_connection_graph(chain_flights)
    late = make_aircraft("LATE", base="A", available_from=dt(5, 0, day=24))
    sol = greedy_baseline(chain_flights, [late], g)
    # The only aircraft is unavailable on the flight day -> nothing assigned.
    assert all(t is None for t in sol.values())


def test_compute_baseline_kpis_shape(chain_flights, one_aircraft):
    kpis = compute_baseline_kpis(chain_flights, one_aircraft)
    assert kpis["algorithm"] == "greedy_baseline"
    assert kpis["total_flights"] == 4
    assert 0.0 <= kpis["coverage"] <= 1.0
    assert kpis["assigned_flights"] == 4
    assert kpis["fuel_cost_usd"] > 0
