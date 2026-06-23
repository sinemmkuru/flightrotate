"""
Optimization endpoint: runs the chosen solver and persists the result.

This is the heart of the API. POST /api/optimize:
  1. Loads flights and aircraft from the database
  2. Builds the Flight Connection Graph
  3. Runs the requested solver (genetic algorithm, CP-SAT, or auto-selected)
  4. Persists the run and its assignments to the database
  5. Returns the run_id so the client can fetch results

Solver selection:
  - "genetic" -> genetic algorithm (heuristic)
  - "cp_sat"  -> CP-SAT exact solver
  - "auto"    -> CP-SAT for small instances, GA for large ones (CP-SAT is
                 exact and fast on small inputs but slows down at scale, so
                 above AUTO_CP_SAT_MAX_FLIGHTS we hand off to the GA).

For simplicity the call is synchronous - the client waits for the run to
finish. Async/background execution will be added later when long runs make
it necessary (see Future Work in the thesis).
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from persistence.database import get_db
from persistence.models import (
    Flight, Aircraft, OptimizationRun, Assignment,
)
from api.schemas.optimization import (
    OptimizeRequest, OptimizeResponse,
)
from engine.graph_builder import build_flight_connection_graph
from engine.genetic_algorithm import run_genetic_algorithm, DEFAULT_GA_PARAMS
from engine.cost_model import flight_fuel_kg, fuel_cost_usd
from engine.solution import DEFAULT_WEIGHTS


router = APIRouter()

# Above this many flights, "auto" hands off to the GA: CP-SAT stays exact and
# fast on small/medium instances but its solve time grows quickly with size.
# Tune this after the scaling benchmark identifies the crossover point.
AUTO_CP_SAT_MAX_FLIGHTS = 400


@router.post("/optimize", response_model=OptimizeResponse)
def optimize(request: OptimizeRequest, db: Session = Depends(get_db)):
    # Guard: don't run on an empty dataset (e.g. only a broken upload was attempted).
    from persistence.models import Flight, Aircraft
    flight_count = db.query(Flight).filter(Flight.deleted_at.is_(None)).count()
    aircraft_count = db.query(Aircraft).filter(Aircraft.deleted_at.is_(None)).count()
    if flight_count == 0 or aircraft_count == 0:
        missing = []
        if flight_count == 0:
            missing.append("flights")
        if aircraft_count == 0:
            missing.append("aircraft")
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot optimize: no {' or '.join(missing)} loaded. "
                "Upload a valid CSV or generate sample data first."
            ),
        )
    """
    Runs an optimization and stores the result.

    Returns the run_id; the client then fetches details via
    GET /api/runs/{run_id} and GET /api/runs/{run_id}/assignments.
    """
    # --- 1. Load data from DB ---
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

    if not flights:
        raise HTTPException(
            status_code=400,
            detail="No flights in database. Upload data or generate a sample first.",
        )
    if not aircraft_list:
        raise HTTPException(
            status_code=400,
            detail="No aircraft in database. Upload data or generate a sample first.",
        )

    # --- 2. Validate weights sum approximately to 1.0 ---
    w = request.weights
    weight_total = w.coverage + w.idle + w.fuel
    if not 0.95 <= weight_total <= 1.05:
        raise HTTPException(
            status_code=400,
            detail=f"Weights must sum to ~1.0 (got {weight_total:.3f})",
        )

    # --- 4. Build the FCG ---
    # Pass per-airport minimum turnarounds so each connection respects the
    # turnaround time of the airport where the aircraft is on the ground.
    from persistence.models import Airport
    airport_turnarounds = {
        ap.iata_code: ap.min_turnaround_min
        for ap in db.query(Airport).filter(Airport.deleted_at.is_(None)).all()
        if ap.min_turnaround_min is not None
    }
    graph = build_flight_connection_graph(
        flights, airport_turnarounds=airport_turnarounds
    )

    # --- 5. Prepare GA parameters ---
    weights_dict = {
        "coverage": w.coverage,
        "idle": w.idle,
        "fuel": w.fuel,
    }
    if request.parameters is not None:
        params_dict = {
            "population_size": request.parameters.population_size,
            "generations": request.parameters.generations,
            "tournament_size": request.parameters.tournament_size,
            "elitism_count": request.parameters.elitism_count,
            "mutation_rate": request.parameters.mutation_rate,
        }
    else:
        params_dict = DEFAULT_GA_PARAMS

    # --- 6. Resolve the solver and run it ---
    # "auto" picks a concrete solver by instance size; the resolved name is what
    # we store and report, so the run record always names a real algorithm.
    requested_algorithm = request.algorithm
    if requested_algorithm == "auto":
        effective_algorithm = (
            "cp_sat" if len(flights) <= AUTO_CP_SAT_MAX_FLIGHTS else "genetic"
        )
    else:
        effective_algorithm = requested_algorithm

    cp_status = None  # CP-SAT solve status (OPTIMAL / FEASIBLE / ...), if used
    if effective_algorithm == "cp_sat":
        from engine.cp_sat_solver import run_cp_sat
        cp_kwargs = {}
        if request.time_limit_seconds is not None:
            cp_kwargs["time_limit_seconds"] = request.time_limit_seconds
        result = run_cp_sat(
            flights=flights,
            aircraft_list=aircraft_list,
            graph=graph,
            weights=weights_dict,
            **cp_kwargs,
        )
        cp_status = result.status
    else:
        result = run_genetic_algorithm(
            flights=flights,
            aircraft_list=aircraft_list,
            graph=graph,
            weights=weights_dict,
            params=params_dict,
            seed=request.seed,
        )

    # --- 7. Persist the run ---
    run_id = str(uuid.uuid4())
    fuel_kg = result.best_fitness.total_fuel_kg
    new_run = OptimizationRun(
        run_id=run_id,
        created_at=datetime.now(timezone.utc),
        algorithm=effective_algorithm,   # store the solver actually used
        weight_idle=w.idle,
        weight_fuel=w.fuel,
        weight_coverage=w.coverage,
        parameters=params_dict,
        coverage=result.best_fitness.coverage,
        idle_minutes=result.best_fitness.total_idle_minutes,
        fuel_kg=fuel_kg,
        fuel_cost_usd=fuel_cost_usd(fuel_kg),
        solve_time_seconds=result.elapsed_seconds,
        total_flights=result.best_fitness.total_flights,
        assigned_flights=result.best_fitness.assigned_count,
    )
    db.add(new_run)

    # --- 8. Persist the assignments ---
    # Group flights by aircraft so we can compute sequence_order and
    # turnaround_minutes for each assigned flight
    flights_by_id = {f.flight_id: f for f in flights}
    by_aircraft: dict[str, list[str]] = {}
    for flight_id, tail in result.best_solution.items():
        if tail is None:
            continue
        by_aircraft.setdefault(tail, []).append(flight_id)
    # Sort each aircraft's flights by departure time
    for tail, ids in by_aircraft.items():
        ids.sort(key=lambda fid: flights_by_id[fid].scheduled_departure)

    MIN_TURNAROUND = 45  # warning threshold in minutes

    for tail, flight_ids in by_aircraft.items():
        for seq, fid in enumerate(flight_ids):
            flight = flights_by_id[fid]
            turnaround = None
            warning = False
            if seq > 0:
                prev_flight = flights_by_id[flight_ids[seq - 1]]
                gap = flight.scheduled_departure - prev_flight.scheduled_arrival
                turnaround = int(gap.total_seconds() / 60)
                warning = turnaround < MIN_TURNAROUND

            db.add(Assignment(
                run_id=run_id,
                flight_id=fid,
                tail_number=tail,
                sequence_order=seq,
                turnaround_minutes=turnaround,
                fuel_kg=flight_fuel_kg(flight.distance_km),
                turnaround_warning=warning,
            ))

    db.commit()

    # --- 9. Build a human-readable solver label for the message ---
    solver_label = effective_algorithm
    if cp_status is not None:
        solver_label = f"cp_sat ({cp_status.lower()})"
    if requested_algorithm == "auto":
        solver_label = f"auto -> {solver_label}"

    return OptimizeResponse(
        run_id=run_id,
        status="completed",
        message=(
            f"Optimization complete in {result.elapsed_seconds:.1f}s. "
            f"Coverage: {result.best_fitness.coverage:.1%}, "
            f"Fitness: {result.best_fitness.fitness:.4f} [{solver_label}]"
        ),
    )