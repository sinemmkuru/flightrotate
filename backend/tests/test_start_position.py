"""
Tests for aircraft start-position continuity (Kademe 2): an aircraft's first
leg must depart from where it actually stands. Enforced via the optional
aircraft_starts map across evaluation, seeding, mutation, CP-SAT and baseline.
"""

from engine.graph_builder import build_flight_connection_graph
from engine.solution import evaluate_solution
from engine.population import build_initial_population
from engine.genetic_operators import _is_assignment_feasible
from engine.genetic_algorithm import run_genetic_algorithm
from engine.cp_sat_solver import run_cp_sat
from engine.baseline import greedy_baseline
from factories import make_flight, make_aircraft, dt

W = {"coverage": 0.5, "idle": 0.25, "robustness": 0.25}
FAST = {"population_size": 30, "generations": 25, "tournament_size": 3,
        "elitism_count": 3, "mutation_rate": 0.3}


def _pair():
    # F1 A->B (08-09) then F2 B->A (10-11): connectable chain that starts at A.
    f1 = make_flight("F1", "A", "B", dt(8), dt(9))
    f2 = make_flight("F2", "B", "A", dt(10), dt(11))
    flights = [f1, f2]
    return flights, {f.flight_id: f for f in flights}, build_flight_connection_graph(flights)


# --- evaluate_solution feasibility ---
def test_eval_first_leg_must_depart_start_airport(chain_flights, flights_by_id):
    g = build_flight_connection_graph(chain_flights)
    sol = {f.flight_id: "T1" for f in chain_flights}  # first leg F1 departs A
    assert evaluate_solution(sol, flights_by_id, g, aircraft_starts={"T1": "A"}).is_feasible is True
    assert evaluate_solution(sol, flights_by_id, g, aircraft_starts={"T1": "B"}).is_feasible is False


def test_eval_no_starts_means_no_position_check(chain_flights, flights_by_id):
    g = build_flight_connection_graph(chain_flights)
    sol = {f.flight_id: "T1" for f in chain_flights}
    assert evaluate_solution(sol, flights_by_id, g, aircraft_starts=None).is_feasible is True


# --- _is_assignment_feasible unit ---
def test_assignment_feasible_first_leg_position():
    _, fbi, g = _pair()
    empty = {"F1": None, "F2": None}
    # Assigning F1 (origin A) as T1's first leg is OK only if T1 starts at A.
    assert _is_assignment_feasible(empty, "F1", "T1", g, fbi, "A") is True
    assert _is_assignment_feasible(empty, "F1", "T1", g, fbi, "B") is False


# --- population seeding ---
def test_population_rotations_start_at_required_airport(chain_flights, flights_by_id):
    g = build_flight_connection_graph(chain_flights)
    ac = [make_aircraft("T1", base="A")]
    pop = build_initial_population(15, ac, flights_by_id, g, seed=3,
                                   aircraft_starts={"T1": "A"})
    for sol in pop:
        legs = sorted([fid for fid, t in sol.items() if t == "T1"],
                      key=lambda fid: flights_by_id[fid].scheduled_departure)
        if legs:
            assert flights_by_id[legs[0]].origin == "A"


def test_population_aircraft_with_no_local_flight_stays_idle(chain_flights, flights_by_id):
    g = build_flight_connection_graph(chain_flights)
    ac = [make_aircraft("T1", base="A")]
    # No flight departs "Z" -> the aircraft can never start -> flies nothing.
    pop = build_initial_population(10, ac, flights_by_id, g, seed=1,
                                   aircraft_starts={"T1": "Z"})
    for sol in pop:
        assert all(t is None for t in sol.values())


# --- CP-SAT ---
def test_cp_sat_respects_start_position():
    flights, _, g = _pair()
    a_at_a = [make_aircraft("T", base="A")]
    a_at_b = [make_aircraft("T", base="B")]
    # Aircraft at A can fly the whole chain F1->F2.
    r_a = run_cp_sat(flights, a_at_a, g, weights=W, aircraft_starts={"T": "A"})
    assert r_a.best_fitness.assigned_count == 2
    # Aircraft at B can only start at B -> covers F2 only; F1 stays uncovered.
    r_b = run_cp_sat(flights, a_at_b, g, weights=W, aircraft_starts={"T": "B"})
    assert r_b.best_solution["F2"] is not None
    assert r_b.best_solution["F1"] is None
    assert r_b.best_fitness.is_feasible is True


# --- baseline ---
def test_baseline_idle_aircraft_starts_at_its_airport():
    flights, _, g = _pair()
    ac = [make_aircraft("T", base="B")]
    sol = greedy_baseline(flights, ac, g, aircraft_starts={"T": "B"})
    assert sol["F1"] is None        # F1 departs A; the aircraft is at B
    assert sol["F2"] == "T"         # F2 departs B; the aircraft can start it


# --- GA end to end ---
def test_ga_respects_start_position_end_to_end(chain_flights):
    g = build_flight_connection_graph(chain_flights)
    ac = [make_aircraft("T1", base="A")]
    res = run_genetic_algorithm(chain_flights, ac, g, W, FAST, seed=2,
                                aircraft_starts={"T1": "A"})
    assert res.best_fitness.is_feasible is True
    legs = sorted([fid for fid, t in res.best_solution.items() if t == "T1"],
                  key=lambda fid: chain_flights and
                  next(f for f in chain_flights if f.flight_id == fid).scheduled_departure)
    if legs:
        first = next(f for f in chain_flights if f.flight_id == legs[0])
        assert first.origin == "A"


def test_ga_stranded_aircraft_flies_nothing(chain_flights):
    g = build_flight_connection_graph(chain_flights)
    ac = [make_aircraft("T1", base="A")]
    res = run_genetic_algorithm(chain_flights, ac, g, W, FAST, seed=2,
                                aircraft_starts={"T1": "Z"})
    assert all(t is None for t in res.best_solution.values())
    assert res.best_fitness.is_feasible is True
