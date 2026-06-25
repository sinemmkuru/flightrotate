"""Tests for ferry / repositioning recovery (Lever B)."""

from engine.ferry import plan_ferries
from factories import make_flight, make_aircraft, dt

# Coordinates for the toy airports (lat, lon). A<->C are ~70 km apart.
COORDS = {
    "A": (40.0, 30.0),
    "B": (41.0, 31.0),
    "C": (40.5, 30.5),
    "D": (41.5, 31.5),
}


def test_ferry_recovers_a_stranded_flight():
    # One idle aircraft at A; the only flight departs C (no aircraft there).
    # A ferry A->C, leaving plenty of time before the 12:00 departure, recovers it.
    f = make_flight("STRAND", "C", "D", dt(12), dt(13))
    ac = [make_aircraft("T1", base="A")]

    out = plan_ferries([f], ac, COORDS)

    assert out["base_coverage"] == 0.0
    assert out["recovered"] == 1
    assert out["ferry_coverage"] == 1.0
    assert out["ferry_legs"] == 1
    leg = out["ferries"][0]
    assert (leg["tail"], leg["from"], leg["to"]) == ("T1", "A", "C")
    assert leg["enables_route"] == "C->D"
    assert out["total_ferry_fuel_kg"] > 0
    assert out["estimated_ferry_cost_usd"] > 0


def test_ferry_infeasible_when_no_time_to_reposition():
    # Same geometry but the flight departs 00:30 — the ferry cannot arrive and
    # turn around in time, so the flight stays unrecoverable (no ferry invented).
    f = make_flight("EARLY", "C", "D", dt(0, 30), dt(1, 30))
    ac = [make_aircraft("T1", base="A")]

    out = plan_ferries([f], ac, COORDS)

    assert out["recovered"] == 0
    assert out["unrecoverable"] == 1
    assert out["ferries"] == []
    assert out["ferry_coverage"] == 0.0


def test_no_ferries_when_base_already_covers_everything():
    # Aircraft at A flies the only flight A->B; nothing is stranded.
    f = make_flight("OK", "A", "B", dt(8), dt(9))
    ac = [make_aircraft("T1", base="A")]

    out = plan_ferries([f], ac, COORDS)

    assert out["base_coverage"] == 1.0
    assert out["recovered"] == 0
    assert out["ferries"] == []
    assert out["total_ferry_km"] == 0


def test_does_not_mutate_inputs():
    f = make_flight("STRAND", "C", "D", dt(12), dt(13))
    ac = [make_aircraft("T1", base="A")]
    n = len(ac)
    plan_ferries([f], ac, COORDS)
    assert len(ac) == n
    assert ac[0].base_airport == "A"  # the real aircraft is untouched
