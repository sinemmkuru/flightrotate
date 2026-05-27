"""
Builds the Flight Connection Graph from flights in the database
and prints a summary. Used to verify the graph builder works.

Usage (from backend folder):
    python scripts/test_graph.py
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from persistence.database import SessionLocal
from persistence.models import Flight
from engine.graph_builder import build_flight_connection_graph, graph_summary


def main():
    db = SessionLocal()
    try:
        # Load all scheduled flights that are not soft-deleted
        flights = (
            db.query(Flight)
            .filter(Flight.status == "scheduled", Flight.deleted_at == None)
            .all()
        )
        print(f"Loaded {len(flights)} flights from database.")

        if len(flights) < 2:
            print("Not enough flights. Run generate_sample_data.py first.")
            return

        print("Building Flight Connection Graph...")
        graph = build_flight_connection_graph(flights)

        summary = graph_summary(graph)
        print("\nGraph summary:")
        print(f"  Nodes (flights)        : {summary['nodes']}")
        print(f"  Edges (connections)    : {summary['edges']}")
        print(f"  Avg connections/flight : {summary['avg_out_degree']}")
        print(f"  Is a valid DAG         : {summary['is_dag']}")
        print(f"  Dead-end flights       : {summary['dead_end_count']}")
        print(f"  Rotation start points  : {summary['start_point_count']}")

        # Show a few example connections
        print("\nSample connections (first 5 edges):")
        for i, (a, b, data) in enumerate(graph.edges(data=True)):
            if i >= 5:
                break
            a_num = graph.nodes[a]["flight_number"]
            b_num = graph.nodes[b]["flight_number"]
            a_route = f"{graph.nodes[a]['origin']}->{graph.nodes[a]['destination']}"
            b_route = f"{graph.nodes[b]['origin']}->{graph.nodes[b]['destination']}"
            print(
                f"  {a_num} ({a_route}) -> {b_num} ({b_route})  "
                f"idle={data['idle_minutes']}min  fuel={data['fuel_cost_kg']}kg"
            )

    finally:
        db.close()


if __name__ == "__main__":
    main()