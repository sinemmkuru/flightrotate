"""
CP-SAT (exact) solver for the aircraft rotation problem.

Models the problem as a minimum-cost path cover on the Flight Connection
Graph (a DAG): choose at most `num_aircraft` vertex-disjoint chains of
flights, maximizing covered flights (primary) and minimizing total idle
time (secondary, which also minimizes APU fuel).

KPIs are computed with the SAME engine.solution.evaluate_solution used by
the genetic algorithm, so GA (heuristic) and CP-SAT (exact) are directly
comparable: only the search method differs, not the cost model.

CP-SAT is exact for small instances; for large ones it returns the best
feasible solution found within the time limit. The solve status (OPTIMAL vs
FEASIBLE) is surfaced so callers can tell when the time limit was hit and the
result is no longer provably optimal.
"""
import time
from dataclasses import dataclass
from typing import Optional

import networkx as nx
from ortools.sat.python import cp_model

from engine.solution import evaluate_solution, build_aircraft_caps, aircraft_can_fly


@dataclass
class CPSATResult:
    """Mirrors the GAResult interface the optimize route expects."""
    best_solution: dict          # flight_id -> tail_number | None
    best_fitness: object         # FitnessBreakdown
    elapsed_seconds: float
    status: str = "UNKNOWN"      # OPTIMAL | FEASIBLE | INFEASIBLE | ... (solver status)


def run_cp_sat(
    flights: list,
    aircraft_list: list,
    graph,
    weights: Optional[dict] = None,
    time_limit_seconds: float = 20.0,
) -> CPSATResult:
    start = time.perf_counter()

    flights_by_id = {f.flight_id: f for f in flights}
    flight_ids = list(flights_by_id.keys())
    num_aircraft = len(aircraft_list)

    # Aircraft availability / maintenance capabilities, and the set of tails that
    # may legally operate each flight. These let the model forbid impossible
    # coverage up front, and let reconstruction assign each chain only to an
    # aircraft that can fly all of its flights.
    tails = [a.tail_number for a in aircraft_list]
    caps = build_aircraft_caps(aircraft_list)
    eligible_sets = {
        fid: {t for t in tails if aircraft_can_fly(caps[t], flights_by_id[fid])}
        for fid in flight_ids
    }

    model = cp_model.CpModel()

    # --- Decision variables ---
    # x[(i, j)] = 1 if flight j immediately follows flight i on one aircraft.
    edges = list(graph.edges())
    x = {(i, j): model.NewBoolVar(f"x_{i}_{j}") for (i, j) in edges}
    # covered[f] = 1 if flight f is assigned to some aircraft.
    covered = {fid: model.NewBoolVar(f"cov_{fid}") for fid in flight_ids}

    in_edges = {fid: [] for fid in flight_ids}
    out_edges = {fid: [] for fid in flight_ids}
    for (i, j) in edges:
        out_edges[i].append(x[(i, j)])
        in_edges[j].append(x[(i, j)])

    # --- Constraints ---
    for fid in flight_ids:
        # At most one predecessor / successor, and only if covered.
        if in_edges[fid]:
            model.Add(sum(in_edges[fid]) <= 1)
            model.Add(sum(in_edges[fid]) <= covered[fid])
        if out_edges[fid]:
            model.Add(sum(out_edges[fid]) <= 1)
            model.Add(sum(out_edges[fid]) <= covered[fid])

    # Number of chains = (covered flights) - (chosen links) <= aircraft count.
    # Each chosen edge merges two chain-segments into one, so it reduces the
    # number of chains by one. The DAG has no cycles, so chains are simple paths.
    model.Add(sum(covered.values()) - sum(x.values()) <= num_aircraft)

    # --- Availability / maintenance eligibility ---
    # A flight no aircraft can legally operate can never be covered.
    for fid in flight_ids:
        if not eligible_sets[fid]:
            model.Add(covered[fid] == 0)
    # Two flights can only be consecutive on one aircraft if at least one
    # aircraft can fly BOTH; otherwise the connecting edge is impossible.
    for (i, j) in edges:
        if not (eligible_sets[i] & eligible_sets[j]):
            model.Add(x[(i, j)] == 0)

    # --- Objective: coverage primary, idle secondary ---
    BIG = 1_000_000  # large enough that one extra covered flight always wins
    idle_terms = [int(graph.edges[i, j]["idle_minutes"]) * x[(i, j)]
                  for (i, j) in edges]
    model.Maximize(BIG * sum(covered.values()) - sum(idle_terms))

    # --- Solve ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_seconds)
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    status_name = solver.StatusName(status)

    # --- Reconstruct the solution dict ---
    solution = {fid: None for fid in flight_ids}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        succ = {}
        has_pred = set()
        for (i, j) in edges:
            if solver.Value(x[(i, j)]) == 1:
                succ[i] = j
                has_pred.add(j)
        starts = [fid for fid in flight_ids
                  if solver.Value(covered[fid]) == 1 and fid not in has_pred]

        # Walk each chain from its start.
        chains = []
        for start_fid in starts:
            chain = []
            cur = start_fid
            seen = set()
            while cur is not None and cur not in seen:
                seen.add(cur)
                chain.append(cur)
                cur = succ.get(cur)
            chains.append(chain)

        # Assign each chain to a DISTINCT aircraft that can fly all of its
        # flights. A chain's eligible tails are the intersection of its flights'
        # eligible sets. We solve this as a maximum-weight bipartite matching
        # (weight = chain length) so covered flights are maximised under the
        # availability/maintenance constraints. When every aircraft is
        # interchangeable (no binding caps), every chain is eligible for every
        # tail and all chains are matched, exactly as before (only the tail
        # labels, which carry no operational meaning, may differ).
        match_graph = nx.Graph()
        for idx, chain in enumerate(chains):
            chain_eligible = set(tails)
            for fid in chain:
                chain_eligible &= eligible_sets[fid]
                if not chain_eligible:
                    break
            for t in chain_eligible:
                match_graph.add_edge(("chain", idx), ("tail", t), weight=len(chain))

        matching = nx.max_weight_matching(match_graph, maxcardinality=False)
        for u, v in matching:
            (chain_idx, tail) = (u[1], v[1]) if u[0] == "chain" else (v[1], u[1])
            for fid in chains[chain_idx]:
                solution[fid] = tail
        # Chains left unmatched (no eligible aircraft available) stay uncovered.

    # KPIs via the SAME evaluator the GA uses -> fair comparison. Passing the
    # capabilities makes the feasibility flag reflect availability/maintenance
    # too, consistent with the genetic algorithm.
    fitness = evaluate_solution(solution, flights_by_id, graph, weights, caps)
    elapsed = time.perf_counter() - start

    print(
        f"[CP-SAT] flights={len(flight_ids)} status={status_name} "
        f"coverage={fitness.coverage * 100:.1f}% elapsed={elapsed:.2f}s "
        f"(time_limit={time_limit_seconds}s)"
    )

    return CPSATResult(
        best_solution=solution,
        best_fitness=fitness,
        elapsed_seconds=elapsed,
        status=status_name,
    )