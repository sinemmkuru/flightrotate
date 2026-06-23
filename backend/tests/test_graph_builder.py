"""Tests for the Flight Connection Graph builder."""

import networkx as nx

from engine.graph_builder import build_flight_connection_graph, graph_summary
from factories import make_flight, dt


def test_chain_has_exactly_the_expected_edges(chain_flights):
    g = build_flight_connection_graph(chain_flights)
    assert g.number_of_nodes() == 4
    assert set(g.edges()) == {("F1", "F2"), ("F2", "F3"), ("F3", "F4")}


def test_graph_is_a_dag(chain_flights):
    g = build_flight_connection_graph(chain_flights)
    assert nx.is_directed_acyclic_graph(g)


def test_edge_idle_minutes_match_ground_gap(chain_flights):
    g = build_flight_connection_graph(chain_flights)
    # F1 arrives 09:00, F2 departs 10:00 -> 60 min ground idle.
    assert g.edges["F1", "F2"]["idle_minutes"] == 60
    assert g.edges["F1", "F2"]["is_overnight"] is False


def test_no_edge_when_airports_do_not_line_up():
    # A->B then A->C: the aircraft would be in B but the next flight departs A.
    f1 = make_flight("F1", "A", "B", dt(8), dt(9))
    f2 = make_flight("F2", "A", "C", dt(10), dt(11))
    g = build_flight_connection_graph([f1, f2])
    assert not g.has_edge("F1", "F2")


def test_turnaround_below_minimum_blocks_edge():
    # 30 min gap < default 45 min turnaround -> no connection.
    f1 = make_flight("F1", "A", "B", dt(8), dt(9))
    f2 = make_flight("F2", "B", "A", dt(9, 30), dt(10, 30))
    g = build_flight_connection_graph([f1, f2])
    assert not g.has_edge("F1", "F2")


def test_per_airport_turnaround_overrides_default():
    # 47 min gap connects under the default 45, but not when airport B needs 50.
    f1 = make_flight("F1", "A", "B", dt(8), dt(9))
    f2 = make_flight("F2", "B", "A", dt(9, 47), dt(10, 47))
    assert build_flight_connection_graph([f1, f2]).has_edge("F1", "F2")
    g = build_flight_connection_graph([f1, f2], airport_turnarounds={"B": 50})
    assert not g.has_edge("F1", "F2")


def test_unknown_airport_falls_back_to_default_turnaround():
    f1 = make_flight("F1", "A", "B", dt(8), dt(9))
    f2 = make_flight("F2", "B", "A", dt(9, 47), dt(10, 47))
    # B not in the map -> default 45 applies, 47 >= 45 connects.
    g = build_flight_connection_graph([f1, f2], airport_turnarounds={"A": 50})
    assert g.has_edge("F1", "F2")


def test_same_day_idle_above_max_blocks_edge():
    # 5h ground gap (> 240 min max idle) on the same day -> not connected.
    f1 = make_flight("F1", "A", "B", dt(8), dt(9))
    f2 = make_flight("F2", "B", "A", dt(14), dt(15))
    g = build_flight_connection_graph([f1, f2])
    assert not g.has_edge("F1", "F2")


def test_overnight_connection_is_flagged_and_not_charged_idle():
    # Land 23:00, depart 08:00 next day: > max idle, crosses midnight, <= 20h.
    f1 = make_flight("F1", "A", "B", dt(22), dt(23))
    f2 = make_flight("F2", "B", "A", dt(8, 0, day=24), dt(9, 0, day=24))
    g = build_flight_connection_graph([f1, f2])
    assert g.has_edge("F1", "F2")
    edge = g.edges["F1", "F2"]
    assert edge["is_overnight"] is True
    assert edge["idle_minutes"] == 0  # APU is off overnight


def test_flight_does_not_connect_to_itself():
    f1 = make_flight("F1", "A", "A", dt(8), dt(9))  # degenerate round trip
    g = build_flight_connection_graph([f1])
    assert not g.has_edge("F1", "F1")


def test_graph_summary_reports_structure(chain_flights):
    g = build_flight_connection_graph(chain_flights)
    s = graph_summary(g)
    assert s["nodes"] == 4
    assert s["edges"] == 3
    assert s["is_dag"] is True
    assert s["dead_end_count"] == 1     # F4 has no onward flight
    assert s["start_point_count"] == 1  # F1 has no predecessor
