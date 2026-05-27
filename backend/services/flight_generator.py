"""
Synthetic flight schedule generator.

Generates realistic Turkish domestic flight schedules with:
  - Hub-weighted airport selection (IST/SAW/ESB get more traffic)
  - Peak-hour bias (morning and evening rushes)
  - Distance-based flight durations (via haversine)
  - Balanced aircraft count relative to flight count

The generator is constrained-random: not pure random, but random within
realistic operational rules. A seed parameter makes output reproducible.
"""

import random
from datetime import datetime, timedelta, date

from persistence.database import SessionLocal
from persistence.models import Airport, Flight, Aircraft
from engine.geo import haversine, estimate_flight_duration_minutes


# Size presets: (flight_count, aircraft_count)
SIZE_PRESETS = {
    "small": (40, 5),
    "medium": (200, 12),
    "large": (700, 35),
}

# Hub weights: probability bias for airport selection.
# Higher weight = more flights through that airport.
HUB_WEIGHTS = {
    "IST": 0.30,
    "SAW": 0.12,
    "ESB": 0.12,
    "ADB": 0.10,
    "AYT": 0.10,
}
# All other operational airports share the remaining probability equally.

# Peak hours (24h format): flights are biased toward these windows.
MORNING_PEAK = (6, 9)
EVENING_PEAK = (17, 20)


def _weighted_airport_choice(operational_codes, weights):
    """
    Picks an airport code using hub weights.
    Hub airports get their assigned weight; the rest split the remainder.
    """
    hub_codes = [c for c in operational_codes if c in weights]
    other_codes = [c for c in operational_codes if c not in weights]

    hub_total = sum(weights[c] for c in hub_codes)
    remainder = 1.0 - hub_total

    population = list(operational_codes)
    probabilities = []
    for code in population:
        if code in weights:
            probabilities.append(weights[code])
        else:
            # Split remaining probability equally among non-hub airports
            probabilities.append(remainder / len(other_codes) if other_codes else 0)

    return random.choices(population, weights=probabilities, k=1)[0]


def _random_departure_time(base_date):
    """
    Generates a departure time biased toward peak hours.
    60% of flights depart during morning or evening peaks.
    """
    if random.random() < 0.6:
        # Peak flight: pick morning or evening window
        if random.random() < 0.5:
            hour = random.randint(*MORNING_PEAK)
        else:
            hour = random.randint(*EVENING_PEAK)
    else:
        # Off-peak flight: any time during operating hours (06:00 - 22:00)
        hour = random.randint(6, 22)

    minute = random.choice([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55])
    return base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)


def generate_flights(size="medium", seed=None, target_date=None):
    """
    Generates a synthetic flight schedule and aircraft fleet, writes them to DB.

    Parameters:
        size: "small", "medium", or "large"
        seed: optional int for reproducible output
        target_date: optional date object; defaults to today

    Returns:
        dict with counts of generated flights and aircraft
    """
    if seed is not None:
        random.seed(seed)

    if size not in SIZE_PRESETS:
        raise ValueError(f"size must be one of {list(SIZE_PRESETS.keys())}")

    flight_count, aircraft_count = SIZE_PRESETS[size]

    if target_date is None:
        target_date = datetime.now()
    base_date = datetime(target_date.year, target_date.month, target_date.day)

    db = SessionLocal()
    try:
        # Load operational airports (is_operational == True)
        operational = (
            db.query(Airport)
            .filter(Airport.is_operational == True, Airport.deleted_at == None)
            .all()
        )
        if len(operational) < 2:
            raise RuntimeError(
                "Need at least 2 operational airports. Run seed_airports.py first."
            )

        airport_map = {a.iata_code: a for a in operational}
        operational_codes = list(airport_map.keys())

        # --- Generate aircraft fleet ---
        # Bases are weighted toward hubs too
        aircraft_list = []
        for i in range(aircraft_count):
            base_code = _weighted_airport_choice(operational_codes, HUB_WEIGHTS)
            tail = f"TC-J{chr(65 + i // 10)}{chr(65 + i % 10)}"  # TC-JAA, TC-JAB, ...
            aircraft = Aircraft(
                tail_number=tail,
                aircraft_type="B737-800",
                base_airport=base_code,
                available_from=base_date.replace(hour=5, minute=0),
                maintenance_due=date(base_date.year + 1, 1, 1),
                status="active",
            )
            aircraft_list.append(aircraft)
            db.add(aircraft)

        # --- Generate flights ---
        flights_added = 0
        for i in range(flight_count):
            origin = _weighted_airport_choice(operational_codes, HUB_WEIGHTS)
            destination = _weighted_airport_choice(operational_codes, HUB_WEIGHTS)
            # Origin and destination must differ
            while destination == origin:
                destination = _weighted_airport_choice(operational_codes, HUB_WEIGHTS)

            o = airport_map[origin]
            d = airport_map[destination]

            distance = haversine(o.latitude, o.longitude, d.latitude, d.longitude)
            duration = estimate_flight_duration_minutes(distance)

            departure = _random_departure_time(base_date)
            arrival = departure + timedelta(minutes=duration)

            flight = Flight(
                flight_id=f"F{i + 1:04d}_{base_date.strftime('%Y%m%d')}",
                flight_number=f"TK{2000 + i}",
                origin=origin,
                destination=destination,
                scheduled_departure=departure,
                scheduled_arrival=arrival,
                distance_km=round(distance),
                status="scheduled",
            )
            db.add(flight)
            flights_added += 1

        db.commit()

        return {
            "size": size,
            "flights_generated": flights_added,
            "aircraft_generated": len(aircraft_list),
            "date": base_date.strftime("%Y-%m-%d"),
        }

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()