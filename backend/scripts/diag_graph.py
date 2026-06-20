"""
Diagnostic: check raw flight connectivity, bypassing the FCG builder.
Run from the backend folder:  python scripts/diag_graph.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from persistence.database import SessionLocal
from persistence.models import Flight
from engine.graph_builder import build_flight_connection_graph

db = SessionLocal()
flights = db.query(Flight).filter(Flight.status == "scheduled").all()
db.close()

# 1) What the builder produces
g = build_flight_connection_graph(flights)
print(f"builder: nodes={g.number_of_nodes()} edges={g.number_of_edges()}")

# 2) Raw data check (independent of the builder)
spatial = 0
feasible = 0
for a in flights:
    for b in flights:
        if a is b:
            continue
        if a.destination == b.origin:
            spatial += 1
            gap = (b.scheduled_departure - a.scheduled_arrival).total_seconds() / 60.0
            if 45 <= gap <= 240:
                feasible += 1
print(f"raw data: spatial_matches={spatial}  time_feasible(45-240min)={feasible}")

# 3) Sample flights
print("sample flights:")
for f in flights[:8]:
    print(f"  {f.flight_id}  {f.origin}->{f.destination}  dep={f.scheduled_departure}  arr={f.scheduled_arrival}")