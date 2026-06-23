"""Tests for the CP-SAT exact solver: optimality, capabilities, weights."""

from engine.graph_builder import build_flight_connection_graph
from engine.cp_sat_solver import run_cp_sat
from factories import make_flight, make_aircraft, dt

W = {"coverage": 0.5, "idle": 0.25, "fuel": 0.25}


def test_solves_small_instance_to_optimality(chain_flights, one_aircraft):
    g = build_flight_connection_graph(chain_flights)
    res = run_cp_sat(chain_flights, one_aircraft, g, weights=W)
    assert res.status == "OPTIMAL"


def test_covers_full_chain_with_one_aircraft(chain_flights, one_aircraft):
    g = build_flight_connection_graph(chain_flights)
    res = run_cp_sat(chain_flights, one_aircraft, g, weights=W)
    assert res.best_fitness.coverage == 1.0
    assert res.best_fitness.is_feasible is True


def test_unavailable_aircraft_is_excluded(chain_flights):
    g = build_flight_connection_graph(chain_flights)
    usable = make_aircraft("OK", base="A", available_from=dt(0))
    late = make_aircraft("LATE", base="A", available_from=dt(5, 0, day=24))
    res = run_cp_sat(chain_flights, [usable, late], g, weights=W)
    assert "LATE" not in res.best_solution.values()
    assert res.best_fitness.is_feasible is True


def _drop_choice_scenario():
    # One aircraft, a forced choice between a short and a long flight that both
    # connect to a shared return leg. Only two of the three can be flown.
    short = make_flight("SHORT", "A", "B", dt(8), dt(9), distance_km=200)
    long_ = make_flight("LONG", "A", "B", dt(8), dt(9), distance_km=1500)
    ret = make_flight("RET", "B", "A", dt(10), dt(11), distance_km=200)
    flights = [short, long_, ret]
    return flights, build_flight_connection_graph(flights)


def test_coverage_stays_primary_regardless_of_weights():
    flights, g = _drop_choice_scenario()
    one = [make_aircraft("OK", base="A")]
    for w in ({"coverage": 0.5, "idle": 0.0, "fuel": 0.5},
              {"coverage": 0.5, "idle": 0.5, "fuel": 0.0}):
        res = run_cp_sat(flights, one, g, weights=w)
        assert res.best_fitness.assigned_count == 2  # max coverable


def test_fuel_weight_drops_the_high_fuel_flight():
    # With fuel weighted heavily, the long (high-fuel) flight is the one dropped.
    flights, g = _drop_choice_scenario()
    one = [make_aircraft("OK", base="A")]
    res = run_cp_sat(flights, one, g, weights={"coverage": 0.5, "idle": 0.0, "fuel": 0.5})
    assert res.best_solution["SHORT"] is not None
    assert res.best_solution["LONG"] is None
    assert res.best_solution["RET"] is not None


def test_weights_none_defaults_without_error(chain_flights, one_aircraft):
    g = build_flight_connection_graph(chain_flights)
    res = run_cp_sat(chain_flights, one_aircraft, g, weights=None)
    assert res.best_fitness.is_feasible is True
    assert res.best_fitness.coverage == 1.0
