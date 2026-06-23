"""Tests for solution representation, fitness, feasibility and capabilities."""

from datetime import date

from engine.graph_builder import build_flight_connection_graph
from engine.solution import (
    evaluate_solution, aircraft_can_fly, build_aircraft_caps,
)
from factories import make_flight, make_aircraft, dt


def _graph(flights):
    return build_flight_connection_graph(flights)


def test_full_chain_is_full_coverage_and_feasible(chain_flights, flights_by_id):
    g = _graph(chain_flights)
    sol = {f.flight_id: "T1" for f in chain_flights}
    b = evaluate_solution(sol, flights_by_id, g)
    assert b.coverage == 1.0
    assert b.assigned_count == 4
    assert b.total_flights == 4
    assert b.is_feasible is True


def test_partial_coverage_fraction(chain_flights, flights_by_id):
    g = _graph(chain_flights)
    sol = {"F1": "T1", "F2": "T1", "F3": None, "F4": None}
    b = evaluate_solution(sol, flights_by_id, g)
    assert b.assigned_count == 2
    assert b.coverage == 0.5


def test_broken_chain_is_infeasible(chain_flights, flights_by_id):
    # F1 (lands B) and F3 (departs A) on one tail: no connecting edge.
    g = _graph(chain_flights)
    sol = {"F1": "T1", "F2": None, "F3": "T1", "F4": None}
    b = evaluate_solution(sol, flights_by_id, g)
    assert b.is_feasible is False


def test_coverage_cannot_be_cheated_by_assigning_few(chain_flights, flights_by_id):
    # Covering all 4 must score higher than covering just 1, even though the
    # single-flight solution has near-perfect per-flight efficiency.
    g = _graph(chain_flights)
    full = {f.flight_id: "T1" for f in chain_flights}
    one = {"F1": "T1", "F2": None, "F3": None, "F4": None}
    f_full = evaluate_solution(full, flights_by_id, g).fitness
    f_one = evaluate_solution(one, flights_by_id, g).fitness
    assert f_full > f_one


def test_overnight_stop_counted():
    f1 = make_flight("F1", "A", "B", dt(22), dt(23))
    f2 = make_flight("F2", "B", "A", dt(8, 0, day=24), dt(9, 0, day=24))
    fbi = {"F1": f1, "F2": f2}
    g = _graph([f1, f2])
    b = evaluate_solution({"F1": "T1", "F2": "T1"}, fbi, g)
    assert b.ron_nights == 1
    assert b.is_feasible is True


# --- aircraft_can_fly rule ---
def test_can_fly_respects_available_from():
    flt = make_flight("F", "A", "B", dt(8), dt(9))
    assert aircraft_can_fly((dt(6), None), flt) is True
    assert aircraft_can_fly((dt(12), None), flt) is False


def test_can_fly_respects_maintenance_due():
    flt = make_flight("F", "A", "B", dt(8), dt(9))
    assert aircraft_can_fly((None, date(2026, 6, 24)), flt) is True   # finishes day before
    assert aircraft_can_fly((None, date(2026, 6, 23)), flt) is False  # arrives on maint day


def test_can_fly_none_bounds_mean_no_constraint():
    flt = make_flight("F", "A", "B", dt(8), dt(9))
    assert aircraft_can_fly((None, None), flt) is True


def test_build_aircraft_caps_maps_tail_to_bounds():
    a = make_aircraft("T1", available_from=dt(6), maintenance_due=date(2027, 1, 1))
    caps = build_aircraft_caps([a])
    assert caps["T1"] == (dt(6), date(2027, 1, 1))


def test_caps_make_unavailable_assignment_infeasible(chain_flights, flights_by_id):
    g = _graph(chain_flights)
    sol = {f.flight_id: "LATE" for f in chain_flights}
    # Aircraft only available from 12:00 but F1 departs 08:00.
    caps = {"LATE": (dt(12), None)}
    b = evaluate_solution(sol, flights_by_id, g, aircraft_caps=caps)
    assert b.is_feasible is False


def test_caps_none_skips_availability_check(chain_flights, flights_by_id):
    g = _graph(chain_flights)
    sol = {f.flight_id: "LATE" for f in chain_flights}
    b = evaluate_solution(sol, flights_by_id, g, aircraft_caps=None)
    assert b.is_feasible is True  # no caps -> availability ignored
