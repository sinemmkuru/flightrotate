"""Tests for delay propagation (reactionary / knock-on delay)."""

import pytest

from engine.delay import propagate_delay
from engine.disruption import run_disruption
from factories import make_flight, make_aircraft, dt


def _two_leg_rotation(second_dep_hour, second_dep_min=0):
    """
    One aircraft: F1 A->B (08:00-09:00) then F2 B->A departing at the given time.
    The gap between F1's arrival (09:00) and F2's departure sets the slack.
    """
    f1 = make_flight("F1", "A", "B", dt(8, 0), dt(9, 0))
    f2 = make_flight("F2", "B", "A", dt(second_dep_hour, second_dep_min), dt(second_dep_hour + 1, second_dep_min))
    flights = [f1, f2]
    fbi = {f.flight_id: f for f in flights}
    solution = {"F1": "T1", "F2": "T1"}
    return fbi, solution


def test_primary_delay_recorded():
    fbi, sol = _two_leg_rotation(11, 0)  # huge slack downstream
    out = propagate_delay(sol, fbi, "F1", 30)
    assert out["delay_minutes"] == 30
    assert out["delayed_flight"]["flight_id"] == "F1"
    assert out["delayed_flight"]["delay_minutes"] == 30


def test_slack_fully_absorbs_delay():
    # F2 departs 11:00; F1 (arr 09:00) delayed 30 -> arr 09:30, earliest F2 dep
    # 09:30+45=10:15 < 11:00 -> F2 not delayed.
    fbi, sol = _two_leg_rotation(11, 0)
    out = propagate_delay(sol, fbi, "F1", 30)
    assert out["knock_on_count"] == 0
    assert out["total_reactionary_delay_min"] == 0
    assert out["flights_delayed"] == 1


def test_tight_turnaround_propagates_fully():
    # F2 departs 09:45, exactly 45 min after F1 arrives (no slack). A 30-min
    # delay on F1 pushes F2 by the full 30 min.
    fbi, sol = _two_leg_rotation(9, 45)
    out = propagate_delay(sol, fbi, "F1", 30)
    assert out["knock_on_count"] == 1
    f2 = out["affected"][1]
    assert f2["flight_id"] == "F2"
    assert f2["delay_minutes"] == 30
    assert out["total_reactionary_delay_min"] == 30
    assert out["total_delay_min"] == 60  # 30 primary + 30 knock-on
    assert out["max_delay_min"] == 30


def test_partial_absorption():
    # F2 departs 10:05 -> 20 min slack over the 45-min turnaround
    # (F1 arr 09:00 + 45 = 09:45; F2 at 10:05 is 20 min later). Delay 30 ->
    # 10 min spills onto F2.
    fbi, sol = _two_leg_rotation(10, 5)
    out = propagate_delay(sol, fbi, "F1", 30)
    assert out["knock_on_count"] == 1
    assert out["affected"][1]["delay_minutes"] == 10


def test_delaying_last_leg_has_no_knock_on():
    fbi, sol = _two_leg_rotation(9, 45)
    out = propagate_delay(sol, fbi, "F2", 30)
    assert out["knock_on_count"] == 0
    assert out["total_delay_min"] == 30


def test_other_aircraft_unaffected():
    f1 = make_flight("F1", "A", "B", dt(8), dt(9))
    f2 = make_flight("F2", "B", "A", dt(9, 45), dt(10, 45))   # same tail as F1
    g1 = make_flight("G1", "A", "C", dt(8), dt(9))            # different tail
    g2 = make_flight("G2", "C", "A", dt(9, 45), dt(10, 45))
    fbi = {f.flight_id: f for f in [f1, f2, g1, g2]}
    sol = {"F1": "T1", "F2": "T1", "G1": "T2", "G2": "T2"}
    out = propagate_delay(sol, fbi, "F1", 30)
    affected_ids = {r["flight_id"] for r in out["affected"]}
    assert affected_ids == {"F1", "F2"}  # T2's legs untouched


def test_per_airport_turnaround_changes_propagation():
    # F2 departs 10:05; with a 70-min turnaround at B the inbound buffer is
    # smaller, so more of the delay spills through than under the default 45.
    fbi, sol = _two_leg_rotation(10, 5)
    default_out = propagate_delay(sol, fbi, "F1", 30)
    strict_out = propagate_delay(sol, fbi, "F1", 30, airport_turnarounds={"B": 70})
    assert strict_out["affected"][1]["delay_minutes"] > default_out["affected"][1]["delay_minutes"]


def test_unknown_flight_raises():
    fbi, sol = _two_leg_rotation(11, 0)
    with pytest.raises(ValueError):
        propagate_delay(sol, fbi, "NOPE", 30)


def test_non_positive_delay_raises():
    fbi, sol = _two_leg_rotation(11, 0)
    with pytest.raises(ValueError):
        propagate_delay(sol, fbi, "F1", 0)


def test_unassigned_flight_raises():
    fbi, sol = _two_leg_rotation(11, 0)
    sol["F1"] = None
    with pytest.raises(ValueError):
        propagate_delay(sol, fbi, "F1", 30)


# --- run_disruption "delay" integration (do-nothing + recovery lenses) ---

def _delay_scenario():
    # One aircraft flying a tight 2-leg rotation, plus a spare aircraft so the
    # optimizer has room to recover by swapping.
    f1 = make_flight("F1", "A", "B", dt(8, 0), dt(9, 0))
    f2 = make_flight("F2", "B", "A", dt(9, 45), dt(10, 45))  # 45-min turnaround, no slack
    flights = [f1, f2]
    aircraft = [make_aircraft("T1", base="A"), make_aircraft("T2", base="B")]
    plan = {"F1": "T1", "F2": "T1"}  # operating plan: both on T1
    return flights, aircraft, plan


def test_run_delay_reports_both_lenses():
    flights, aircraft, plan = _delay_scenario()
    out = run_disruption(flights, aircraft, dtype="delay", flight_id="F1",
                         delay_minutes=30, plan_solution=plan)
    assert out["disruption"]["type"] == "delay"
    assert out["delay_propagation"]["knock_on_count"] == 1   # F2 pushed
    assert "before" in out and "after" in out
    assert isinstance(out["summary"], str) and out["summary"]


def test_run_delay_requires_positive_minutes():
    flights, aircraft, plan = _delay_scenario()
    with pytest.raises(ValueError):
        run_disruption(flights, aircraft, dtype="delay", flight_id="F1",
                       delay_minutes=0, plan_solution=plan)


def test_run_delay_unknown_flight_raises():
    flights, aircraft, plan = _delay_scenario()
    with pytest.raises(ValueError):
        run_disruption(flights, aircraft, dtype="delay", flight_id="GHOST",
                       delay_minutes=30, plan_solution=plan)


def test_run_delay_without_plan_falls_back_to_fresh_solve():
    # plan_solution=None -> run_disruption solves a plan itself; should still work.
    flights, aircraft, _ = _delay_scenario()
    out = run_disruption(flights, aircraft, dtype="delay", flight_id="F1",
                         delay_minutes=30, plan_solution=None)
    assert out["delay_propagation"]["delay_minutes"] == 30
