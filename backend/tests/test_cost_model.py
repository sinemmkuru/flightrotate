"""Tests for the B737-800 fuel cost model."""

from engine.cost_model import (
    flight_fuel_kg, idle_fuel_kg, connection_fuel_kg, fuel_cost_usd,
    FUEL_TAXI, FUEL_TAKEOFF_CLIMB, FUEL_DESCENT_LANDING,
    FUEL_CRUISE_PER_KM, FUEL_APU_PER_MINUTE, FUEL_PRICE_USD_PER_KG,
)

FIXED = FUEL_TAXI + FUEL_TAKEOFF_CLIMB + FUEL_DESCENT_LANDING


def test_flight_fuel_zero_distance_is_fixed_segments():
    assert flight_fuel_kg(0) == FIXED


def test_flight_fuel_adds_cruise_per_km():
    assert flight_fuel_kg(400) == FIXED + 400 * FUEL_CRUISE_PER_KM


def test_flight_fuel_is_monotonic_in_distance():
    assert flight_fuel_kg(1000) > flight_fuel_kg(500) > flight_fuel_kg(0)


def test_idle_fuel_proportional_to_minutes():
    assert idle_fuel_kg(30) == 30 * FUEL_APU_PER_MINUTE


def test_idle_fuel_zero_or_negative_is_zero():
    assert idle_fuel_kg(0) == 0.0
    assert idle_fuel_kg(-5) == 0.0


def test_connection_fuel_is_flight_plus_idle():
    assert connection_fuel_kg(400, 30) == flight_fuel_kg(400) + idle_fuel_kg(30)


def test_fuel_cost_usd():
    assert fuel_cost_usd(1000) == 1000 * FUEL_PRICE_USD_PER_KG
    assert fuel_cost_usd(0) == 0.0
