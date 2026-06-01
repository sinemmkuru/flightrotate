"""
Quick smoke test: generate a small initial population and evaluate
each solution's fitness. Used to verify the building blocks work
together correctly before wiring up the full GA.

Usage (from backend folder):
    python scripts/test_population.py
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from persistence.database import SessionLocal
from persistence.models import Flight, Aircraft
from engine.graph_builder import build_flight_connection_graph
from engine.population import build_initial_population
from engine.solution import evaluate_solution


def main():
    db = SessionLocal()
    try:
        flights = (
            db.query(Flight)
            .filter(Flight.status == "scheduled", Flight.deleted_at == None)
            .all()
        )
        aircraft_list = (
            db.query(Aircraft)
            .filter(Aircraft.status == "active", Aircraft.deleted_at == None)
            .all()
        )
        print(f"Loaded {len(flights)} flights and {len(aircraft_list)} aircraft.")

        # Build the FCG
        print("Building Flight Connection Graph...")
        graph = build_flight_connection_graph(flights)
        flights_by_id = {f.flight_id: f for f in flights}

        # Build a small population of 5 random solutions
        print("Building initial population (size = 5)...")
        population = build_initial_population(
            population_size=5,
            aircraft_list=aircraft_list,
            flights_by_id=flights_by_id,
            graph=graph,
            seed=42,
        )

        # Evaluate each solution
        print("\nEvaluation of each solution:")
        print(f"{'#':<3} {'fitness':>10} {'coverage':>10} {'assigned':>10} "
              f"{'idle_min':>10} {'fuel_kg':>10} {'feasible':>10}")
        for i, sol in enumerate(population):
            r = evaluate_solution(sol, flights_by_id, graph)
            print(
                f"{i:<3} {r.fitness:>10.4f} {r.coverage:>10.2%} "
                f"{r.assigned_count:>10} {r.total_idle_minutes:>10} "
                f"{r.total_fuel_kg:>10.0f} {str(r.is_feasible):>10}"
            )

    finally:
        db.close()


if __name__ == "__main__":
    main()