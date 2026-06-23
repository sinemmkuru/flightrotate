"""Tests for great-circle distance and flight-duration estimation."""

import math

from engine.geo import haversine, estimate_flight_duration_minutes


def test_haversine_same_point_is_zero():
    assert haversine(41.0, 29.0, 41.0, 29.0) == 0.0


def test_haversine_is_symmetric():
    a = haversine(41.0, 29.0, 39.9, 32.8)
    b = haversine(39.9, 32.8, 41.0, 29.0)
    assert math.isclose(a, b, rel_tol=1e-9)


def test_haversine_positive_for_distinct_points():
    assert haversine(41.0, 29.0, 39.9, 32.8) > 0


def test_haversine_known_distance_one_degree_latitude():
    # One degree of latitude is ~111 km anywhere on the globe.
    d = haversine(0.0, 0.0, 1.0, 0.0)
    assert 110 < d < 112


def test_duration_includes_fixed_overhead():
    # At cruise speed, 750 km takes ~1h cruise + 30 min overhead = 90 min.
    assert estimate_flight_duration_minutes(750) == 90


def test_duration_zero_distance_is_overhead_only():
    # No distance -> only the fixed takeoff/landing manoeuvre overhead (30 min).
    assert estimate_flight_duration_minutes(0) == 30


def test_duration_monotonic_in_distance():
    assert (estimate_flight_duration_minutes(1500)
            > estimate_flight_duration_minutes(500))
