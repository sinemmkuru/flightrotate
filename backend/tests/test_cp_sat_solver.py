"""Tests for the CP-SAT exact solver: optimality, capabilities, weights."""

from engine.graph_builder import build_flight_connection_graph
from engine.cp_sat_solver import run_cp_sat
from factories import make_flight, make_aircraft, dt

W = {"coverage": 0.5, "idle": 0.25, "robustness": 0.25}


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
    for w in ({"coverage": 0.5, "idle": 0.0, "robustness": 0.5},
              {"coverage": 0.5, "idle": 0.5, "robustness": 0.0}):
        res = run_cp_sat(flights, one, g, weights=w)
        assert res.best_fitness.assigned_count == 2  # max coverable


def _robustness_choice_scenario():
    # One aircraft at A flies F1 (A->B), then exactly one of two B->A returns:
    # a TIGHT turnaround (50 min: 5 min slack over the 45 min minimum -> risky)
    # or a LOOSE one (90 min: ample buffer). Both give coverage 2/3, so only the
    # idle-vs-robustness tie-break decides which leg is flown.
    f1 = make_flight("F1", "A", "B", dt(8), dt(9), distance_km=400)
    tight = make_flight("F2_TIGHT", "B", "A", dt(9, 50), dt(10, 50), distance_km=400)
    loose = make_flight("F3_LOOSE", "B", "A", dt(10, 30), dt(11, 30), distance_km=400)
    flights = [f1, tight, loose]
    return flights, build_flight_connection_graph(flights)


def test_robustness_weight_prefers_the_looser_turnaround():
    flights, g = _robustness_choice_scenario()
    one = [make_aircraft("OK", base="A")]
    # Robustness-heavy: avoid the tight turnaround -> keep the comfortable leg.
    res = run_cp_sat(flights, one, g,
                     weights={"coverage": 0.5, "idle": 0.0, "robustness": 0.5})
    assert res.best_solution["F3_LOOSE"] is not None
    assert res.best_solution["F2_TIGHT"] is None
    # Idle-heavy: minimize ground time -> keep the tighter (less idle) leg.
    res2 = run_cp_sat(flights, one, g,
                      weights={"coverage": 0.5, "idle": 0.5, "robustness": 0.0})
    assert res2.best_solution["F2_TIGHT"] is not None
    assert res2.best_solution["F3_LOOSE"] is None


def test_weights_none_defaults_without_error(chain_flights, one_aircraft):
    g = build_flight_connection_graph(chain_flights)
    res = run_cp_sat(chain_flights, one_aircraft, g, weights=None)
    assert res.best_fitness.is_feasible is True
    assert res.best_fitness.coverage == 1.0
