"""
Lightweight factories for engine tests.

The engine reads only plain attributes off flight/aircraft objects and never
touches the database, so tests build them as tiny SimpleNamespace stand-ins with
exactly the fields the engine consumes. Kept in its own importable module (not
conftest, which pytest loads specially) so test files can `from factories import`.
"""

from datetime import datetime
from types import SimpleNamespace


def dt(hour, minute=0, day=23, month=6, year=2026):
    """Build a datetime on the test's reference day (2026-06-23 by default)."""
    return datetime(year, month, day, hour, minute)


def make_flight(flight_id, origin, destination, dep, arr,
                distance_km=400, flight_number=None):
    """A minimal Flight stand-in carrying the fields the engine reads."""
    return SimpleNamespace(
        flight_id=flight_id,
        flight_number=flight_number or flight_id,
        origin=origin,
        destination=destination,
        scheduled_departure=dep,
        scheduled_arrival=arr,
        distance_km=distance_km,
        status="scheduled",
    )


def make_aircraft(tail, base="A", available_from=None, maintenance_due=None):
    """A minimal Aircraft stand-in. available_from defaults to the day's start."""
    return SimpleNamespace(
        tail_number=tail,
        aircraft_type="B737-800",
        base_airport=base,
        available_from=available_from if available_from is not None else dt(0, 0),
        maintenance_due=maintenance_due,
        status="active",
    )
