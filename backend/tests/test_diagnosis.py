"""Tests for the unassigned-flight diagnosis (decision-support reason codes)."""

from engine.graph_builder import build_flight_connection_graph
from engine.diagnosis import diagnose_unassigned, summarize_reasons
from factories import make_flight, make_aircraft, dt


def _reasons(rows):
    return {r["flight_id"]: r["reason"] for r in rows}


def test_capacity_when_aircraft_starts_at_origin():
    # One aircraft based at A, two flights it cannot both start: the uncovered
    # one is reachable (an aircraft stands at A), so the reason is capacity.
    f = make_flight("CAP", "A", "B", dt(8), dt(9))
    fbi = {"CAP": f}
    g = build_flight_connection_graph([f])
    ac = [make_aircraft("T1", base="A")]
    rows = diagnose_unassigned({"CAP": None}, fbi, g, ac, {"T1": "A"})
    assert _reasons(rows)["CAP"] == "capacity"


def test_location_when_no_aircraft_at_origin_and_no_inbound():
    # Flight departs C; no aircraft is based at C and nothing flies into C, so
    # there is simply no aircraft there -> location (positioning needed).
    f = make_flight("LOC", "C", "D", dt(8), dt(9))
    fbi = {"LOC": f}
    g = build_flight_connection_graph([f])
    ac = [make_aircraft("T1", base="A")]
    rows = diagnose_unassigned({"LOC": None}, fbi, g, ac, {"T1": "A"})
    assert _reasons(rows)["LOC"] == "location"


def test_capacity_when_covered_inbound_feeds_the_origin():
    # An aircraft starts at A, flies A->B (covered), so B is reachable. The
    # uncovered B->A is then a capacity problem, not location, even though no
    # aircraft is *based* at B.
    out = make_flight("OUT", "A", "B", dt(8), dt(9))
    back = make_flight("BACK", "B", "A", dt(10), dt(11))
    fbi = {"OUT": out, "BACK": back}
    g = build_flight_connection_graph([out, back])
    ac = [make_aircraft("T1", base="A")]
    rows = diagnose_unassigned({"OUT": "T1", "BACK": None}, fbi, g, ac, {"T1": "A"})
    assert _reasons(rows)["BACK"] == "capacity"


def test_availability_when_no_eligible_aircraft():
    # The only aircraft becomes available after the flight departs -> no eligible
    # aircraft at all, so the reason is availability (not location/capacity).
    f = make_flight("AV", "A", "B", dt(8), dt(9))
    fbi = {"AV": f}
    g = build_flight_connection_graph([f])
    ac = [make_aircraft("T1", base="A", available_from=dt(12))]
    rows = diagnose_unassigned({"AV": None}, fbi, g, ac, {"T1": "A"})
    assert _reasons(rows)["AV"] == "availability"


def test_assigned_flights_are_not_reported():
    f = make_flight("OK", "A", "B", dt(8), dt(9))
    fbi = {"OK": f}
    g = build_flight_connection_graph([f])
    ac = [make_aircraft("T1", base="A")]
    rows = diagnose_unassigned({"OK": "T1"}, fbi, g, ac, {"T1": "A"})
    assert rows == []


def test_summary_counts_and_total():
    loc = make_flight("LOC", "C", "D", dt(8), dt(9))
    cap = make_flight("CAP", "A", "B", dt(8), dt(9))
    fbi = {"LOC": loc, "CAP": cap}
    g = build_flight_connection_graph([loc, cap])
    ac = [make_aircraft("T1", base="A")]
    rows = diagnose_unassigned({"LOC": None, "CAP": None}, fbi, g, ac, {"T1": "A"})
    s = summarize_reasons(rows)
    assert s["total"] == 2
    assert s["by_reason"] == {"capacity": 1, "location": 1}
