"""
Flight Connection Graph (FCG) builder.

The FCG is a Directed Acyclic Graph (DAG):
  - Each node is a flight.
  - A directed edge from flight A to flight B means the same aircraft
    can fly B immediately after A.

An edge A -> B is feasible when:
  1. Spatial:  A.destination == B.origin (aircraft is in the right place)
  2. Temporal: B departs at least `min_turnaround` minutes after A arrives,
     and the ground gap is either a same-day idle (<= max_idle) or a single
     overnight rest (RON, <= max_overnight that crosses to the next day).

Edge attributes:
  - idle_minutes : productive ground time charged as idle / APU fuel.
                   For an overnight (RON) connection this is 0, because the
                   aircraft is parked and the APU is shut down overnight.
  - fuel_cost_kg : fuel of flying B plus APU fuel during the idle period
  - is_overnight : True if this connection is an overnight rest (RON)
  - gap_minutes  : the true wall-clock gap between A's arrival and B's
                   departure (equals idle_minutes for same-day connections)

Scalability
-----------
Instead of checking every ordered pair of flights (O(n^2), which becomes
billions of comparisons for multi-month horizons), flights are bucketed by
their ORIGIN airport, each bucket sorted by departure time. For a flight A we
only look at flights departing A's destination airport within the feasible
time window [arrival + min_turnaround, arrival + max_overnight], located with a
binary search. The 20-hour window bounds the candidate set to roughly a single
day of that airport's departures, so the build stays near O(n log n) regardless
of how many days the schedule spans. The resulting graph is identical to the
naive O(n^2) build.

The graph is acyclic because edges only ever point forward in time.
"""

import bisect
from collections import defaultdict
from datetime import timedelta

import networkx as nx

from engine.cost_model import connection_fuel_kg

# Default minimum turnaround time for B737-800 (minutes).
# Used when an airport-specific value is not available.
DEFAULT_MIN_TURNAROUND = 45

# Maximum sensible same-day idle time between two flights (minutes).
# Same-day connections with longer idle are not added: an aircraft sitting
# idle for many hours mid-day is operationally pointless and only bloats the
# graph.
MAX_IDLE_MINUTES = 240  # 4 hours

# Maximum ground gap (minutes) treated as a single overnight rest (RON).
# A gap that exceeds MAX_IDLE_MINUTES but stays within this bound and crosses
# to the next calendar day is an overnight stop: the aircraft parks for the
# night and resumes the next operational morning. Longer gaps are NOT
# connected — that would mean parking idle for more than one night;
# intermediate flights should fill the rotation, or the rotation ends there.
MAX_OVERNIGHT_MINUTES = 1200  # 20 hours


def build_flight_connection_graph(
    flights,
    min_turnaround=DEFAULT_MIN_TURNAROUND,
    max_idle=MAX_IDLE_MINUTES,
    max_overnight=MAX_OVERNIGHT_MINUTES,
):
    """
    Builds the Flight Connection Graph from a list of Flight objects.

    Uses airport bucketing + a time-window binary search so the build scales
    to multi-month schedules without an O(n^2) pairwise comparison.

    Parameters:
        flights: list of Flight ORM objects (must have flight_id, origin,
                 destination, scheduled_departure, scheduled_arrival,
                 distance_km)
        min_turnaround: minimum ground time required between two flights (min)
        max_idle: maximum same-day idle gap to still form a connection (min)
        max_overnight: maximum overnight (RON) gap to still connect (min)

    Returns:
        A networkx.DiGraph where nodes are flight_ids and edges are feasible
        connections with idle_minutes, fuel_cost_kg, is_overnight and
        gap_minutes attributes.
    """
    graph = nx.DiGraph()

    # Add every flight as a node, storing its data for later use.
    for flight in flights:
        graph.add_node(
            flight.flight_id,
            flight_number=flight.flight_number,
            origin=flight.origin,
            destination=flight.destination,
            departure=flight.scheduled_departure,
            arrival=flight.scheduled_arrival,
            distance_km=flight.distance_km,
        )

    # --- Bucket flights by ORIGIN airport, sorted by departure time. ---
    # departures_by_origin[X] = flights departing X, ascending by departure.
    # dep_times_by_origin[X]  = parallel list of departure datetimes (for bisect).
    departures_by_origin = defaultdict(list)
    for f in flights:
        departures_by_origin[f.origin].append(f)
    for origin in departures_by_origin:
        departures_by_origin[origin].sort(key=lambda f: f.scheduled_departure)
    dep_times_by_origin = {
        origin: [f.scheduled_departure for f in bucket]
        for origin, bucket in departures_by_origin.items()
    }

    # --- For each flight A, scan only the feasible window at its destination. ---
    for a in flights:
        candidates = departures_by_origin.get(a.destination)
        if not candidates:
            continue  # nothing departs where A lands -> A is a dead end

        dep_times = dep_times_by_origin[a.destination]

        # B must depart within [arrival + min_turnaround, arrival + max_overnight].
        earliest = a.scheduled_arrival + timedelta(minutes=min_turnaround)
        latest = a.scheduled_arrival + timedelta(minutes=max_overnight)
        lo = bisect.bisect_left(dep_times, earliest)
        hi = bisect.bisect_right(dep_times, latest)

        for idx in range(lo, hi):
            b = candidates[idx]
            if b.flight_id == a.flight_id:
                continue  # a flight cannot connect to itself

            # Gap is already guaranteed in [min_turnaround, max_overnight] by
            # the window; classify it as same-day idle or an overnight rest.
            gap = (b.scheduled_departure - a.scheduled_arrival).total_seconds() / 60.0
            crosses_to_next_day = (
                b.scheduled_departure.date() > a.scheduled_arrival.date()
            )

            if not crosses_to_next_day:
                # Same calendar day: an ordinary turnaround / ground idle.
                if gap > max_idle:
                    continue  # too long a mid-day gap for a sensible connection
                idle_minutes = gap
                is_overnight = False
            else:
                if gap <= max_idle:
                    # A short gap that merely crosses midnight (e.g.
                    # 23:40 -> 00:30) is still a normal turnaround.
                    idle_minutes = gap
                    is_overnight = False
                else:
                    # Remain-over-night: APU is shut down and the aircraft is
                    # parked, so this gap is NOT productive idle and must not
                    # be charged as idle time or APU fuel. Recorded separately.
                    idle_minutes = 0.0
                    is_overnight = True

            # idle_minutes is 0 for overnight, so the APU fuel term inside
            # connection_fuel_kg is naturally zero.
            fuel = connection_fuel_kg(b.distance_km, idle_minutes)
            graph.add_edge(
                a.flight_id,
                b.flight_id,
                idle_minutes=idle_minutes,
                fuel_cost_kg=fuel,
                is_overnight=is_overnight,
                gap_minutes=gap,
            )

    return graph


def graph_summary(graph):
    """
    Returns a summary dict describing the graph - useful for verification.

    Parameters:
        graph: a networkx.DiGraph produced by build_flight_connection_graph

    Returns:
        dict with node count, edge count, density, and connectivity info
    """
    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()

    # Average out-degree: how many onward connections a flight has on average
    if node_count > 0:
        avg_out_degree = edge_count / node_count
    else:
        avg_out_degree = 0.0

    # Flights with no onward connection (dead ends in the rotation)
    dead_ends = [n for n in graph.nodes if graph.out_degree(n) == 0]
    # Flights that no other flight can connect into (rotation start points)
    unreachable = [n for n in graph.nodes if graph.in_degree(n) == 0]

    return {
        "nodes": node_count,
        "edges": edge_count,
        "avg_out_degree": round(avg_out_degree, 2),
        "is_dag": nx.is_directed_acyclic_graph(graph),
        "dead_end_count": len(dead_ends),
        "start_point_count": len(unreachable),
    }