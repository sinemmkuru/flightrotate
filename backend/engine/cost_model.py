"""
Fuel cost model for the Boeing 737-800.

Computes fuel consumption using a segment-based model:
    Total fuel = Taxi + Takeoff/Climb + Cruise + Descent/Landing + APU(idle)

Design rationale:
  APU (Auxiliary Power Unit) fuel is proportional to idle time on the ground.
  This means minimizing idle time genuinely reduces fuel burn. A pure
  "distance x rate" model would make optimization decisions irrelevant to
  fuel (total distance flown is fixed). The segment-based model ties the
  optimizer's routing decisions directly to fuel consumption.

All values are approximate B737-800 figures compiled from public sources.
"""

# --- B737-800 fuel constants (kilograms) ---

# Fixed per-flight segments (do not depend on distance)
FUEL_TAXI = 175.0            # taxi out + taxi in, combined
FUEL_TAKEOFF_CLIMB = 700.0   # takeoff roll + climb to cruise altitude
FUEL_DESCENT_LANDING = 350.0 # descent + approach + landing

# Distance-dependent cruise rate
FUEL_CRUISE_PER_KM = 2.5     # kg of fuel burned per km at cruise

# APU (ground idle) consumption rate
FUEL_APU_PER_MINUTE = 2.0    # kg of fuel burned per minute of ground idle

# Jet fuel price assumption (USD per kg) - used for cost reporting
FUEL_PRICE_USD_PER_KG = 0.82


def flight_fuel_kg(distance_km: float) -> float:
    """
    Fuel burned by a single flight, in kilograms.

    Includes the fixed segments (taxi, climb, descent) plus the
    distance-dependent cruise burn. Does NOT include APU/idle fuel,
    which is computed separately based on ground time between flights.

    Parameters:
        distance_km: flight distance in kilometers

    Returns:
        Fuel burned (kg)
    """
    fixed = FUEL_TAXI + FUEL_TAKEOFF_CLIMB + FUEL_DESCENT_LANDING
    cruise = distance_km * FUEL_CRUISE_PER_KM
    return fixed + cruise


def idle_fuel_kg(idle_minutes: float) -> float:
    """
    Fuel burned by the APU while an aircraft sits idle on the ground
    between two consecutive flights.

    Parameters:
        idle_minutes: ground idle time in minutes

    Returns:
        APU fuel burned (kg)
    """
    if idle_minutes <= 0:
        return 0.0
    return idle_minutes * FUEL_APU_PER_MINUTE


def connection_fuel_kg(distance_km: float, idle_minutes: float) -> float:
    """
    Total fuel cost of flying one flight after an idle period.

    This is the value used as edge weight in the Flight Connection Graph:
    it captures both the cruise/segment fuel of the flight itself and the
    APU fuel consumed while waiting for it.

    Parameters:
        distance_km: distance of the flight being flown
        idle_minutes: idle time before this flight departs

    Returns:
        Combined fuel (kg)
    """
    return flight_fuel_kg(distance_km) + idle_fuel_kg(idle_minutes)


def fuel_cost_usd(fuel_kg: float) -> float:
    """
    Converts a fuel quantity (kg) to an estimated cost in USD.

    Parameters:
        fuel_kg: fuel quantity in kilograms

    Returns:
        Estimated cost in USD
    """
    return fuel_kg * FUEL_PRICE_USD_PER_KG