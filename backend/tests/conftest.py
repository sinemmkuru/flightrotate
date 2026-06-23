"""
Shared pytest fixtures for the engine test suite.

The flight/aircraft factories live in factories.py (an ordinary importable
module). This conftest puts both the backend root (so `import engine.*` works)
and the tests directory (so `from factories import ...` works) on sys.path, then
exposes a handful of ready-made scenarios as fixtures.
"""

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
# Backend root first so engine.* imports resolve; tests dir so factories imports do.
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(TESTS_DIR))

import pytest  # noqa: E402

from factories import make_flight, make_aircraft, dt  # noqa: E402


@pytest.fixture
def flight_factory():
    return make_flight


@pytest.fixture
def aircraft_factory():
    return make_aircraft


# ---------------------------------------------------------------------------
# Canonical small schedule: a single feasible 4-flight rotation
#   F1 A->B 08:00-09:00 | F2 B->A 10:00-11:00 | F3 A->C 12:00-13:30 | F4 C->A 14:30-16:00
# Consecutive ground gaps are all 60 min (>= 45 turnaround, <= 240 idle, same day),
# so F1->F2->F3->F4 is one connectable chain a single aircraft can fly end to end.
# No other feasible edges exist (origins/destinations don't otherwise line up).
# ---------------------------------------------------------------------------
@pytest.fixture
def chain_flights():
    return [
        make_flight("F1", "A", "B", dt(8, 0), dt(9, 0), distance_km=400),
        make_flight("F2", "B", "A", dt(10, 0), dt(11, 0), distance_km=400),
        make_flight("F3", "A", "C", dt(12, 0), dt(13, 30), distance_km=600),
        make_flight("F4", "C", "A", dt(14, 30), dt(16, 0), distance_km=600),
    ]


@pytest.fixture
def flights_by_id(chain_flights):
    return {f.flight_id: f for f in chain_flights}


@pytest.fixture
def one_aircraft():
    return [make_aircraft("TC-AAA", base="A")]


@pytest.fixture
def two_aircraft():
    return [make_aircraft("TC-AAA", base="A"), make_aircraft("TC-BBB", base="A")]
