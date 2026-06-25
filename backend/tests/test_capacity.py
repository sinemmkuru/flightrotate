"""Tests for the capacity-planning analysis (Lever A)."""

from engine.capacity import suggest_capacity, LEASE_COST_USD_PER_DAY
from factories import make_flight, make_aircraft, dt


def test_suggestion_recovers_full_coverage_at_the_right_airport():
    # Two simultaneous departures from A and C with a single aircraft at A. The
    # C->D flight cannot be covered (no aircraft at C); the analysis should
    # propose +1 aircraft AT C and reach full coverage.
    f1 = make_flight("F1", "A", "B", dt(8), dt(9))
    f2 = make_flight("F2", "C", "D", dt(8), dt(9))
    ac = [make_aircraft("T1", base="A")]

    out = suggest_capacity([f1, f2], ac)

    assert out["available"] is True
    assert out["full_coverage"] is False
    assert out["current"]["coverage"] < 1.0
    assert out["add_aircraft"] >= 1
    assert out["by_airport"].get("C", 0) >= 1
    assert out["suggested"]["coverage"] == 1.0
    assert out["estimated_daily_cost_usd"] == out["add_aircraft"] * LEASE_COST_USD_PER_DAY


def test_no_suggestion_when_already_full_coverage():
    f1 = make_flight("F1", "A", "B", dt(8), dt(9))
    ac = [make_aircraft("T1", base="A")]

    out = suggest_capacity([f1], ac)

    assert out["full_coverage"] is True
    assert out["add_aircraft"] == 0
    assert out["by_airport"] == {}
    assert out["estimated_daily_cost_usd"] == 0.0


def test_does_not_mutate_inputs():
    f1 = make_flight("F1", "A", "B", dt(8), dt(9))
    f2 = make_flight("F2", "C", "D", dt(8), dt(9))
    ac = [make_aircraft("T1", base="A")]
    before = len(ac)

    suggest_capacity([f1, f2], ac)

    assert len(ac) == before  # the real fleet list is untouched
