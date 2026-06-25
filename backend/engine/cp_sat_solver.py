"""
CP-SAT (exact) solver for the aircraft rotation problem.

Models the problem as a minimum-cost path cover on the Flight Connection
Graph (a DAG): choose at most `num_aircraft` vertex-disjoint chains of
flights, maximizing covered flights (primary) and optimizing a weighted blend
of low idle time and high turnaround robustness (secondary).

KPIs are computed with the SAME engine.solution.evaluate_solution used by
the genetic algorithm, so GA (heuristic) and CP-SAT (exact) are directly
comparable: only the search method differs, not the cost model.

CP-SAT is exact for small instances; for large ones it returns the best
feasible solution found within the time limit. The solve status (OPTIMAL vs
FEASIBLE) is surfaced so callers can tell when the time limit was hit and the
result is no longer provably optimal.
"""
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

import networkx as nx
from ortools.sat.python import cp_model

from engine.solution import (
    evaluate_solution, build_aircraft_caps, aircraft_can_fly,
    DEFAULT_WEIGHTS, IDLE_PER_FLIGHT_REFERENCE, ROBUSTNESS_RISK_REFERENCE,
)


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
    aircraft_starts: Optional[dict] = None,
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

    # --- Start-position capacity (when aircraft positions are known) ---
    # A chain can only BEGIN at an airport that has an aircraft standing there.
    # start[f] = covered[f] - (chosen predecessors of f) equals 1 iff f opens a
    # chain, so the number of chains opening at each airport is capped by the
    # aircraft positioned there. Modelling this (rather than only filtering at
    # reconstruction) lets the solver fall back to a shorter coverable chain
    # instead of building one no positioned aircraft can fly.
    if aircraft_starts:
        cap_at: dict = defaultdict(int)
        for t in tails:
            ap = aircraft_starts.get(t)
            if ap is not None:
                cap_at[ap] += 1
        flights_by_origin: dict = defaultdict(list)
        for fid in flight_ids:
            flights_by_origin[flights_by_id[fid].origin].append(fid)
        for origin, fids in flights_by_origin.items():
            starts_here = sum(covered[fid] - sum(in_edges[fid]) for fid in fids)
            model.Add(starts_here <= cap_at.get(origin, 0))

    # --- Objective: coverage primary, weighted idle + robustness secondary ---
    # Coverage is the primary (lexicographic) goal: COVERAGE_REWARD is far larger
    # than any achievable secondary cost, so the solver always covers as many
    # flights as it can first, and every covered flight earns the SAME reward (so
    # the objective simply maximises the covered-flight count). The genetic
    # algorithm uses the SAME lexicographic order (engine.solution: covered-flight
    # count dominates the efficiency tie-break), so GA and CP-SAT optimise the same
    # preference and a GA-vs-CP-SAT comparison reflects only the search method, not
    # a different objective. This matches the business priority (a published
    # schedule must be flown) and rules out the degenerate "cover few flights to
    # minimise totals" solution.
    #
    # The secondary objective honours the user's idle AND robustness weights,
    # normalised against the same references the GA uses (engine.solution): each
    # chosen connection carries its idle time (efficiency) plus its tight-turnaround
    # risk (robustness), which pull in opposite directions. Fuel is not in the
    # objective — with a fixed schedule trip fuel is constant, so it is a reported
    # KPI, not a lever. Coefficients are integer-scaled because CP-SAT requires an
    # integer objective.
    w = weights or DEFAULT_WEIGHTS
    w_idle = w.get("idle", DEFAULT_WEIGHTS["idle"])
    w_robust = w.get("robustness", DEFAULT_WEIGHTS["robustness"])
    SCALE = 1000
    COVERAGE_REWARD = SCALE * 100_000  # dominates any secondary cost

    def _edge_cost(idle_min, tight_risk):
        # Idle time (efficiency) and tight-connection risk (robustness), each
        # weighted and normalised against the GA's references.
        idle_term = w_idle * SCALE * idle_min / IDLE_PER_FLIGHT_REFERENCE
        risk_term = w_robust * SCALE * tight_risk / ROBUSTNESS_RISK_REFERENCE
        return int(round(idle_term + risk_term))

    cover_terms = [COVERAGE_REWARD * covered[fid] for fid in flight_ids]
    secondary_terms = [
        _edge_cost(
            graph.edges[i, j]["idle_minutes"],
            graph.edges[i, j].get("tight_risk", 0.0),
        ) * x[(i, j)]
        for (i, j) in edges
    ]
    model.Maximize(sum(cover_terms) - sum(secondary_terms))

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
            # Start position: an aircraft can only take a chain that begins where
            # it currently stands. chain[0] is the chain's first (earliest) leg.
            if aircraft_starts:
                first_origin = flights_by_id[chain[0]].origin
                chain_eligible = {
                    t for t in chain_eligible
                    if aircraft_starts.get(t) is None
                    or aircraft_starts[t] == first_origin
                }
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
    fitness = evaluate_solution(
        solution, flights_by_id, graph, weights, caps, aircraft_starts
    )
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