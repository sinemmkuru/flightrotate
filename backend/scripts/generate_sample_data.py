"""
Runs the synthetic flight generator and prints a summary.

Usage (from backend folder):
    python scripts/generate_sample_data.py
    python scripts/generate_sample_data.py small
    python scripts/generate_sample_data.py medium
    python scripts/generate_sample_data.py large

A fixed seed (42) is used so the output is reproducible.
"""

import sys
from pathlib import Path

# Add backend/ to the import path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from services.flight_generator import generate_flights
from persistence.database import SessionLocal
from persistence.models import Flight, Aircraft, Airport


def main():
    # Read size from command line argument, default to "medium"
    size = sys.argv[1] if len(sys.argv) > 1 else "medium"

    print(f"Generating synthetic data (size = {size})...")
    result = generate_flights(size=size, seed=42)

    print(f"\nGeneration complete:")
    print(f"  Date            : {result['date']}")
    print(f"  Flights created : {result['flights_generated']}")
    print(f"  Aircraft created: {result['aircraft_generated']}")

    # Verification: read back from DB and show a few sample flights
    db = SessionLocal()
    try:
        total_flights = db.query(Flight).count()
        total_aircraft = db.query(Aircraft).count()
        print(f"\nDatabase totals:")
        print(f"  Flights in DB : {total_flights}")
        print(f"  Aircraft in DB: {total_aircraft}")

        print(f"\nSample flights (first 5):")
        sample = db.query(Flight).limit(5).all()
        for f in sample:
            dep = f.scheduled_departure.strftime("%H:%M")
            arr = f.scheduled_arrival.strftime("%H:%M")
            print(
                f"  {f.flight_number}: {f.origin} -> {f.destination}  "
                f"{dep}-{arr}  ({f.distance_km} km)"
            )

        print(f"\nSample aircraft (first 5):")
        sample_ac = db.query(Aircraft).limit(5).all()
        for a in sample_ac:
            print(f"  {a.tail_number} ({a.aircraft_type}) - base: {a.base_airport}")

    finally:
        db.close()


if __name__ == "__main__":
    main()