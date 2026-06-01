"""
Runs the genetic algorithm on the current dataset and prints results.

Usage (from backend folder):
    python scripts/run_optimization.py
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from persistence.database import SessionLocal
from persistence.models import Flight, Aircraft
from engine.graph_builder import build_flight_connection_graph
from engine.genetic_algorithm import run_genetic_algorithm


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

        print("Building Flight Connection Graph...")
        graph = build_flight_connection_graph(flights)
        print(f"  Nodes: {graph.number_of_nodes()}, edges: {graph.number_of_edges()}")

        print("\nRunning genetic algorithm...")
        print("  (population=100, generations=200, this takes a minute)")
        result = run_genetic_algorithm(
            flights=flights,
            aircraft_list=aircraft_list,
            graph=graph,
            seed=42,
        )

        b = result.best_fitness
        print(f"\nBest solution found in {result.elapsed_seconds:.1f} seconds:")
        print(f"  Generations run    : {result.generations_run}")
        print(f"  Fitness            : {b.fitness:.4f}")
        print(f"  Coverage           : {b.coverage:.2%}  ({b.assigned_count}/{b.total_flights})")
        print(f"  Total idle minutes : {b.total_idle_minutes}")
        print(f"  Total fuel (kg)    : {b.total_fuel_kg:.0f}")
        print(f"  Feasible           : {b.is_feasible}")

        # Quick convergence snapshot: how did the best fitness change?
        c = result.convergence
        print(f"\nConvergence (best fitness over time):")
        print(f"  Gen   0: {c[0]:.4f}")
        print(f"  Gen  50: {c[50]:.4f}")
        print(f"  Gen 100: {c[100]:.4f}")
        print(f"  Gen 150: {c[150]:.4f}")
        print(f"  Gen 199: {c[-1]:.4f}")

        # Improvement metrics for context
        initial = c[0]
        final = c[-1]
        improvement = final - initial
        print(f"\nImprovement from gen 0 to final: {improvement:+.4f}")

    finally:
        db.close()


if __name__ == "__main__":
    main()