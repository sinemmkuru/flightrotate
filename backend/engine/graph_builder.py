"""
Flight Connection Graph (FCG) builder.

The FCG is a Directed Acyclic Graph (DAG):
  - Each node is a flight.
  - A directed edge from flight A to flight B means the same aircraft
    can fly B immediately after A.

An edge A -> B is feasible when:
  1. Spatial:  A.destination == B.origin (aircraft is in the right place)
  2. Temporal: B departs at least `min_turnaround` minutes after A arrives

Edge attributes:
  - idle_minutes : ground time between A's arrival and B's departure
  - fuel_cost_kg : fuel of flying B plus APU fuel during the idle period

The graph is acyclic because edges only ever point forward in time.
"""

import networkx as nx

from engine.cost_model import connection_fuel_kg

# Default minimum turnaround time for B737-800 (minutes).
# Used when an airport-specific value is not available.
DEFAULT_MIN_TURNAROUND = 45

# Maximum sensible idle time between two flights (minutes).
# Connections with longer idle are not added: an aircraft sitting idle
# for many hours is operationally pointless and only bloats the graph.
MAX_IDLE_MINUTES = 240  # 4 hours

# Maximum ground gap (minutes) treated as a single overnight rest (RON).
# A gap that exceeds MAX_IDLE_MINUTES but stays within this bound is an
# overnight stop: the aircraft parks for the night and resumes the next
# operational morning. Longer gaps are NOT connected — that would mean
# parking idle for more than one night; intermediate flights should fill
# the rotation, or the rotation simply ends there.
MAX_OVERNIGHT_MINUTES = 1200  # 20 hours


def build_flight_connection_graph(
    flights,
    min_turnaround=DEFAULT_MIN_TURNAROUND,
    max_idle=MAX_IDLE_MINUTES,
    max_overnight=MAX_OVERNIGHT_MINUTES,
):
    """
    Builds the Flight Connection Graph from a list of Flight objects.

    Parameters:
        flights: list of Flight ORM objects (must have flight_id, origin,
                 destination, scheduled_departure, scheduled_arrival,
                 distance_km)
        min_turnaround: minimum ground time required between two flights
                        (minutes)

    Returns:
        A networkx.DiGraph where nodes are flight_ids and edges are
        feasible connections with idle_minutes and fuel_cost_kg attributes.
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

    # Check every ordered pair (A, B) for a feasible connection.
    for a in flights:
        for b in flights:
            if a.flight_id == b.flight_id:
                continue  # a flight cannot connect to itself

            # Condition 1 - Spatial: A must land where B departs
            if a.destination != b.origin:
                continue

            # Condition 2 - Temporal: enough time for turnaround, then classify
        # the gap as either same-day ground idle or an overnight rest (RON).
        gap = (b.scheduled_departure - a.scheduled_arrival).total_seconds() / 60.0
        if gap < min_turnaround:
            continue

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
            if gap > max_overnight:
                continue  # more than one night of parking — don't connect
            if gap <= max_idle:
                # A short gap that merely crosses midnight (e.g. 23:40 -> 00:30)
                # is still a normal turnaround, not an overnight rest.
                idle_minutes = gap
                is_overnight = False
            else:
                # Remain-over-night: APU is shut down and the aircraft is
                # parked, so this gap is NOT productive idle and must not be
                # charged as idle time or APU fuel. Recorded separately.
                idle_minutes = 0.0
                is_overnight = True

            # Feasible connection found - compute edge weight
            fuel = connection_fuel_kg(b.distance_km, idle)

            graph.add_edge(
            a.flight_id, b.flight_id,
            idle_minutes=idle_minutes,          # was: idle
            is_overnight=is_overnight,          # NEW
            gap_minutes=gap,                     # NEW (true wall-clock gap)
            # ... mevcut diğer attribute'ları (fuel/weight) AYNEN bırak,
            #     ama içlerinde idle kullanıyorsan onları da idle_minutes yap
            #edge'in fuel/weight'ini idle'dan hesaplıyorsan onu da idle_minutes'a çevir 
            # #— böylece overnight kenar yakıt cezası almaz (APU kapalı, doğru).
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