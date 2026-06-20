"""
Synthetic flight schedule generator.

Generates realistic Turkish domestic flight schedules with:
  - Hub-weighted airport selection (IST/SAW/ESB get more traffic)
  - Peak-hour bias (morning and evening rushes)
  - Distance-based flight durations (via haversine)
  - Balanced aircraft count relative to flight count
  - Multi-day schedules (num_days): the same fleet flies a fresh randomized
    schedule each operational day, so aircraft rotations can chain across
    nights via overnight (RON) edges in the Flight Connection Graph.

The generator is constrained-random: not pure random, but random within
realistic operational rules. A seed parameter makes output reproducible.
"""

import random
from datetime import datetime, timedelta, date

from persistence.database import SessionLocal
from persistence.models import Airport, Flight, Aircraft
from engine.geo import haversine, estimate_flight_duration_minutes


# Size presets: (flights_PER_DAY, aircraft_count).
# Aircraft-to-flight ratio of ~1/8 matches realistic fleet sizing:
# a B737-800 can typically fly 8-10 legs per day. The flight count is the
# PER-DAY load; total flights = flights_per_day * num_days.
SIZE_PRESETS = {
    "small": (40, 8),
    "medium": (200, 25),
    "large": (700, 70),
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
# Probability that a flight departs during a peak window.
# Lower value = more even distribution across the operating day.
PEAK_HOUR_PROBABILITY = 0.35


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


def _random_departure_time(day_base):
    """
    Generates a departure time biased toward peak hours but balanced
    enough to allow long aircraft rotations across the operating day.

    Without sufficient mid-day flights, an aircraft that lands at 09:30
    cannot connect to a next flight until evening, breaking its rotation.
    The PEAK_HOUR_PROBABILITY constant controls how strongly we cluster
    flights at the peaks.

    `day_base` is a datetime at 00:00 of the operational day; the returned
    departure is placed on that same day.
    """
    if random.random() < PEAK_HOUR_PROBABILITY:
        # Peak flight
        if random.random() < 0.5:
            hour = random.randint(*MORNING_PEAK)
        else:
            hour = random.randint(*EVENING_PEAK)
    else:
        # Off-peak flight: uniformly across the operating day (06:00 - 22:00)
        hour = random.randint(6, 22)

    minute = random.choice([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55])
    return day_base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def generate_flights(size="medium", seed=None, target_date=None, num_days=1):
    """
    Generates a synthetic flight schedule and aircraft fleet, writes them to DB.

    Parameters:
        size: "small", "medium", or "large"
        seed: optional int for reproducible output
        target_date: optional date object; defaults to today (the first day)
        num_days: number of consecutive operational days to generate (>= 1).
                  flight_count from SIZE_PRESETS is the PER-DAY load, so the
                  total number of flights is flight_count * num_days. The
                  fleet is created once and shared across all days.

    Returns:
        dict with counts and the start/end dates of the generated schedule
    """
    if seed is not None:
        random.seed(seed)

    if size not in SIZE_PRESETS:
        raise ValueError(f"size must be one of {list(SIZE_PRESETS.keys())}")

    if num_days < 1:
        raise ValueError("num_days must be >= 1")

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

        # --- Generate aircraft fleet (created ONCE, shared across all days) ---
        # Bases are weighted toward hubs too.
        aircraft_list = []
        for i in range(aircraft_count):
            # Distribute aircraft across hubs proportionally to their
            # share of flight origins. This matches real airline practice:
            # bigger hubs need more aircraft based there.
            #
            # IST gets ~30% of flights -> ~30% of aircraft.
            # Hubs are listed in HUB_WEIGHTS in priority order.
            hub_order = list(HUB_WEIGHTS.keys())  # IST, SAW, ESB, ADB, AYT
            # Weighted slot assignment: hub priority * total aircraft
            hub_quotas = {
                hub: max(1, round(HUB_WEIGHTS[hub] * aircraft_count))
                for hub in hub_order
            }
            # Build a flat list of hub slots respecting the quotas
            hub_slots = []
            for hub, quota in hub_quotas.items():
                hub_slots.extend([hub] * quota)
            # Assign each aircraft to a hub slot, falling back to weighted
            # random for any extras beyond the quota total
            if i < len(hub_slots):
                base_code = hub_slots[i]
            else:
                base_code = _weighted_airport_choice(operational_codes, HUB_WEIGHTS)
            tail = f"TC-J{chr(65 + i // 10)}{chr(65 + i % 10)}"  # TC-JAA, TC-JAB, ...
            aircraft = Aircraft(
                tail_number=tail,
                aircraft_type="B737-800",
                base_airport=base_code,
                # Available from 05:00 on the first day; rotations may then
                # continue across subsequent days via overnight connections.
                available_from=base_date.replace(hour=5, minute=0),
                maintenance_due=date(base_date.year + 1, 1, 1),
                status="active",
            )
            aircraft_list.append(aircraft)
            db.add(aircraft)

        # --- Generate flights, one operational day at a time ---
        # Each day gets a fresh randomized schedule (the RNG keeps advancing),
        # so days differ but the whole run stays reproducible under `seed`.
        flights_added = 0
        flight_seq = 0  # globally unique flight-number counter across all days
        for day_index in range(num_days):
            day_base = base_date + timedelta(days=day_index)
            day_tag = day_base.strftime("%Y%m%d")
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

                departure = _random_departure_time(day_base)
                arrival = departure + timedelta(minutes=duration)

                flight = Flight(
                    # flight_id is unique via the per-day date suffix;
                    # flight_number is globally unique via flight_seq.
                    flight_id=f"F{i + 1:04d}_{day_tag}",
                    flight_number=f"TK{2000 + flight_seq}",
                    origin=origin,
                    destination=destination,
                    scheduled_departure=departure,
                    scheduled_arrival=arrival,
                    distance_km=round(distance),
                    status="scheduled",
                )
                db.add(flight)
                flights_added += 1
                flight_seq += 1

        db.commit()

        end_date = base_date + timedelta(days=num_days - 1)
        return {
            "size": size,
            "num_days": num_days,
            "flights_generated": flights_added,
            "aircraft_generated": len(aircraft_list),
            "date": base_date.strftime("%Y-%m-%d"),        # start (kept for the UI)
            "start_date": base_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
        }

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()