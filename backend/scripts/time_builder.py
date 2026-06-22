"""
Times ONLY the FCG builder (not the diagnostic's O(n^2) raw-data check).
Run from the backend folder:  python scripts/time_builder.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from persistence.database import SessionLocal
from persistence.models import Flight
from engine.graph_builder import build_flight_connection_graph, graph_summary

db = SessionLocal()
flights = db.query(Flight).filter(Flight.status == "scheduled").all()
db.close()

t = time.perf_counter()
graph = build_flight_connection_graph(flights)
build_time = time.perf_counter() - t

print(f"flights={len(flights)}  build_time={build_time:.3f}s")
print(graph_summary(graph))