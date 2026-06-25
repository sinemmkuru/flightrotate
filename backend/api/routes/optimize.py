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

import threading
import uuid
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from persistence.database import get_db, SessionLocal
from persistence.models import (
    Flight, Aircraft, OptimizationRun, Assignment,
)
from api.schemas.optimization import (
    OptimizeRequest, OptimizeResponse,
)
from engine.graph_builder import build_flight_connection_graph
from engine.genetic_algorithm import run_genetic_algorithm, DEFAULT_GA_PARAMS
from engine.cost_model import flight_fuel_kg, fuel_cost_usd
from engine.solution import DEFAULT_WEIGHTS, build_aircraft_caps, evaluate_solution
from api.routes.plans import get_active_plan_id
from api.auth import require_admin


router = APIRouter()

# Above this many flights, "auto" hands off to the GA: CP-SAT stays exact and
# fast on small/medium instances but its solve time grows quickly with size.
# Tune this after the scaling benchmark identifies the crossover point.
AUTO_CP_SAT_MAX_FLIGHTS = 400


@router.post("/optimize", response_model=OptimizeResponse)
def optimize(request: OptimizeRequest, db: Session = Depends(get_db),
             _admin: str = Depends(require_admin)):
    """Run an optimization synchronously and return when it finishes."""
    return _execute_optimization(request, db)


def _execute_optimization(
    request: OptimizeRequest, db: Session, progress_callback=None
) -> OptimizeResponse:
    # Everything is scoped to the active plan (flights/runs); the fleet is global.
    plan_id = get_active_plan_id(db)
    # Guard: don't run on an empty dataset (e.g. only a broken upload was attempted).
    from persistence.models import Flight, Aircraft
    flight_count = (
        db.query(Flight)
        .filter(Flight.deleted_at.is_(None), Flight.plan_id == plan_id)
        .count()
    )
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
        .filter(
            Flight.status == "scheduled", Flight.deleted_at == None,  # noqa: E711
            Flight.plan_id == plan_id,
        )
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
    weight_total = w.coverage + w.idle + w.robustness
    if not 0.95 <= weight_total <= 1.05:
        raise HTTPException(
            status_code=400,
            detail=f"Weights must sum to ~1.0 (got {weight_total:.3f})",
        )

    # --- 3. Resolve the planning reference time ("now" by default) ---
    # Flights departing before this are PAST: they are not re-optimized, but
    # locked to their tail from the most recent prior run (history). Only
    # flights at or after the reference time are optimized. This mirrors a real
    # OCC, which never re-plans a flight whose departure has already passed.
    reference_time = request.reference_time or datetime.now()
    future_flights = [f for f in flights if f.scheduled_departure >= reference_time]
    past_flights = [f for f in flights if f.scheduled_departure < reference_time]

    if not future_flights:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No flights at or after the reference time "
                f"({reference_time.isoformat()}); there is nothing to optimize."
            ),
        )

    # Lock past flights to their tail from the operating plan: the published
    # plan of record if there is one, otherwise the most recent run.
    prior_run = (
        db.query(OptimizationRun)
        .filter(
            OptimizationRun.deleted_at.is_(None),
            OptimizationRun.plan_id == plan_id,
        )
        .order_by(
            (OptimizationRun.status == "published").desc(),
            OptimizationRun.created_at.desc(),
        )
        .first()
    )
    locked_past: dict[str, str] = {}
    if past_flights and prior_run is not None:
        past_ids = {f.flight_id for f in past_flights}
        for a in (
            db.query(Assignment)
            .filter(Assignment.run_id == prior_run.run_id)
            .all()
        ):
            if a.flight_id in past_ids:
                locked_past[a.flight_id] = a.tail_number

    # --- 4. Build the FCG ---
    # Per-airport minimum turnarounds so each connection respects the turnaround
    # of the airport where the aircraft is on the ground. The optimization graph
    # spans only the FUTURE flights; a full-flight graph is built afterwards to
    # score the combined (locked-past + optimized-future) plan.
    from persistence.models import Airport
    airport_turnarounds = {
        ap.iata_code: ap.min_turnaround_min
        for ap in db.query(Airport).filter(Airport.deleted_at.is_(None)).all()
        if ap.min_turnaround_min is not None
    }
    graph = build_flight_connection_graph(
        future_flights, airport_turnarounds=airport_turnarounds
    )

    # --- 4b. Carry each aircraft's position/availability across the boundary ---
    # An aircraft that flew locked past legs now stands at that last leg's
    # destination and is free only after it lands (+ turnaround). The future
    # optimisation starts it from there: its first future leg must depart that
    # airport (aircraft_starts) at/after that time (effective available_from).
    # Aircraft with no locked past keep their base (a soft preference, so they
    # are left out of aircraft_starts) and their normal availability.
    DEFAULT_TURN = 45
    past_by_tail: dict[str, list[str]] = {}
    for fid, tail in locked_past.items():
        past_by_tail.setdefault(tail, []).append(fid)
    past_fbi = {f.flight_id: f for f in past_flights}

    effective_aircraft = []
    aircraft_starts: dict[str, str] = {}
    for ac in aircraft_list:
        legs = past_by_tail.get(ac.tail_number)
        if legs:
            last = max(
                (past_fbi[fid] for fid in legs),
                key=lambda f: f.scheduled_arrival,
            )
            start_airport = last.destination
            turn = airport_turnarounds.get(start_airport, DEFAULT_TURN)
            eff_available_from = last.scheduled_arrival + timedelta(minutes=turn)
            aircraft_starts[ac.tail_number] = start_airport  # position is fixed
        else:
            start_airport = ac.base_airport          # soft; not pinned
            eff_available_from = ac.available_from
        effective_aircraft.append(SimpleNamespace(
            tail_number=ac.tail_number,
            aircraft_type=ac.aircraft_type,
            base_airport=start_airport,
            available_from=eff_available_from,
            maintenance_due=ac.maintenance_due,
            status=ac.status,
        ))

    # --- 5. Prepare GA parameters ---
    weights_dict = {
        "coverage": w.coverage,
        "idle": w.idle,
        "robustness": w.robustness,
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

    # --- 6. Resolve the solver (by FUTURE instance size) and run it ---
    # "auto" picks a concrete solver by instance size; the resolved name is what
    # we store and report, so the run record always names a real algorithm.
    requested_algorithm = request.algorithm
    if requested_algorithm == "auto":
        effective_algorithm = (
            "cp_sat" if len(future_flights) <= AUTO_CP_SAT_MAX_FLIGHTS else "genetic"
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
            flights=future_flights,
            aircraft_list=effective_aircraft,
            graph=graph,
            weights=weights_dict,
            aircraft_starts=aircraft_starts,
            **cp_kwargs,
        )
        cp_status = result.status
    else:
        result = run_genetic_algorithm(
            flights=future_flights,
            aircraft_list=effective_aircraft,
            graph=graph,
            weights=weights_dict,
            params=params_dict,
            seed=request.seed,
            aircraft_starts=aircraft_starts,
            progress_callback=progress_callback,
        )

    # --- 7. Combine locked past + optimized future into one plan ---
    all_flights_by_id = {f.flight_id: f for f in flights}
    combined_solution: dict[str, str | None] = {fid: None for fid in all_flights_by_id}
    for fid, tail in result.best_solution.items():
        combined_solution[fid] = tail
    combined_solution.update(locked_past)  # the past is history; it wins

    # Score the WHOLE displayed plan (locked past + optimized future) so the
    # dashboard KPIs match the Gantt. The optimization graph only spans future
    # flights, so a full-flight graph is needed here.
    full_graph = build_flight_connection_graph(
        flights, airport_turnarounds=airport_turnarounds
    )
    caps = build_aircraft_caps(aircraft_list)
    plan_bd = evaluate_solution(
        combined_solution, all_flights_by_id, full_graph, weights_dict, caps
    )

    # --- 8. Persist the run ---
    run_id = str(uuid.uuid4())
    fuel_kg = plan_bd.total_fuel_kg
    params_record = {
        **params_dict,
        "reference_time": reference_time.isoformat(),
        "locked_past_flights": len(locked_past),
        "future_flights": len(future_flights),
    }
    new_run = OptimizationRun(
        run_id=run_id,
        plan_id=plan_id,
        created_at=datetime.now(timezone.utc),
        algorithm=effective_algorithm,   # store the solver actually used
        weight_idle=w.idle,
        weight_robustness=w.robustness,
        weight_coverage=w.coverage,
        parameters=params_record,
        coverage=plan_bd.coverage,
        idle_minutes=plan_bd.total_idle_minutes,
        fuel_kg=fuel_kg,
        fuel_cost_usd=fuel_cost_usd(fuel_kg),
        solve_time_seconds=result.elapsed_seconds,
        total_flights=plan_bd.total_flights,
        assigned_flights=plan_bd.assigned_count,
    )
    db.add(new_run)

    # --- 9. Persist the assignments (combined plan) ---
    # Group flights by aircraft so we can compute sequence_order and
    # turnaround_minutes for each assigned flight.
    flights_by_id = all_flights_by_id
    by_aircraft: dict[str, list[str]] = {}
    for flight_id, tail in combined_solution.items():
        if tail is None:
            continue
        by_aircraft.setdefault(tail, []).append(flight_id)
    # Sort each aircraft's flights by departure time
    for tail, ids in by_aircraft.items():
        ids.sort(key=lambda fid: flights_by_id[fid].scheduled_departure)

    # A connection is "tight" when its ground time is within TIGHT_TURNAROUND_BUFFER
    # minutes of the MINIMUM turnaround for the airport where the aircraft sits
    # (flight.origin) — the same per-airport minimum the connection graph enforces,
    # so the warning is consistent with feasibility instead of a global 45 min flag
    # (which never fired at default-45 airports and false-alarmed at faster ones).
    # An overnight (RON) connection is a parked rest, not a turnaround: its long
    # ground gap is not reported as turnaround_minutes and never warns.
    TIGHT_TURNAROUND_BUFFER = 15  # minutes above the airport minimum still "tight"

    for tail, flight_ids in by_aircraft.items():
        for seq, fid in enumerate(flight_ids):
            flight = flights_by_id[fid]
            turnaround = None
            warning = False
            if seq > 0:
                prev_fid = flight_ids[seq - 1]
                prev_flight = flights_by_id[prev_fid]
                # Read the connection's overnight classification from the full-plan
                # graph (single source of truth) so a parked-overnight gap isn't
                # surfaced as an ~800-minute "turnaround".
                is_overnight = (
                    full_graph.has_edge(prev_fid, fid)
                    and full_graph.edges[prev_fid, fid].get("is_overnight", False)
                )
                if not is_overnight:
                    gap = flight.scheduled_departure - prev_flight.scheduled_arrival
                    turnaround = int(gap.total_seconds() / 60)
                    ap_min = airport_turnarounds.get(flight.origin, DEFAULT_TURN)
                    warning = turnaround < ap_min + TIGHT_TURNAROUND_BUFFER

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

    # The message reports the OPTIMISATION's own result (the future flights it
    # actually solved). When there is no locked past this equals the whole plan,
    # so non-time-aware runs read exactly as before. The persisted KPIs above
    # cover the whole displayed plan (locked past + optimised future).
    if locked_past:
        message = (
            f"Optimization complete in {result.elapsed_seconds:.1f}s. "
            f"Future coverage: {result.best_fitness.coverage:.1%} "
            f"({len(future_flights)} open flights) · "
            f"{len(locked_past)} past flight(s) locked [{solver_label}]"
        )
    else:
        message = (
            f"Optimization complete in {result.elapsed_seconds:.1f}s. "
            f"Coverage: {result.best_fitness.coverage:.1%} "
            f"({result.best_fitness.assigned_count}/{result.best_fitness.total_flights} flights) "
            f"[{solver_label}]"
        )
    return OptimizeResponse(run_id=run_id, status="completed", message=message)


# ---------------------------------------------------------------------------
# Asynchronous optimization with live progress
# ---------------------------------------------------------------------------
# Large instances (e.g. 500+ flights via the genetic algorithm) can take longer
# than a client request should block for. POST /optimize/async starts the same
# optimization in a background thread and returns a job id immediately; the
# client polls GET /optimize/status/{job_id} for live progress (the GA reports
# its best fitness each generation) and the final run_id.
#
# Jobs live in an in-process registry. This is per-worker and not persisted,
# which is fine for the single-worker dev/prototype server; a multi-worker
# deployment would back this with a shared store (Redis, the DB, etc.).
_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()


def _set_job(job_id: str, **fields) -> None:
    with _JOBS_LOCK:
        _JOBS.setdefault(job_id, {}).update(fields)


@router.post("/optimize/async")
def optimize_async(request: OptimizeRequest, db: Session = Depends(get_db),
                   _admin: str = Depends(require_admin)):
    """
    Start an optimization in the background; return a job id at once.

    Poll GET /optimize/status/{job_id}: while running it carries the GA's
    generation/best-fitness progress; when done it carries the run_id (and the
    same message the synchronous endpoint returns), or an error.
    """
    # Fast, synchronous validation so obviously-bad requests fail immediately
    # instead of as a background error.
    flight_count = (
        db.query(Flight)
        .filter(Flight.deleted_at.is_(None), Flight.plan_id == get_active_plan_id(db))
        .count()
    )
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
    w = request.weights
    if not 0.95 <= (w.coverage + w.idle + w.robustness) <= 1.05:
        raise HTTPException(
            status_code=400,
            detail=f"Weights must sum to ~1.0 (got {w.coverage + w.idle + w.robustness:.3f})",
        )

    total_generations = (
        request.parameters.generations
        if request.parameters is not None
        else DEFAULT_GA_PARAMS["generations"]
    )
    job_id = str(uuid.uuid4())
    _set_job(
        job_id,
        status="running",
        algorithm=request.algorithm,
        progress={
            "phase": "starting",
            "generation": 0,
            "total_generations": total_generations,
            "best_fitness": None,
        },
        run_id=None,
        message=None,
        error=None,
    )

    def worker():
        # The background thread outlives the request, so it owns its own DB
        # session (check_same_thread=False makes cross-thread access safe).
        worker_db = SessionLocal()
        try:
            def cb(generation, best_fitness):
                _set_job(job_id, progress={
                    "phase": "running",
                    "generation": generation + 1,
                    "total_generations": total_generations,
                    "best_fitness": round(float(best_fitness), 4),
                })

            resp = _execute_optimization(request, worker_db, progress_callback=cb)
            _set_job(
                job_id, status="completed", run_id=resp.run_id,
                message=resp.message,
                progress={
                    "phase": "completed",
                    "generation": total_generations,
                    "total_generations": total_generations,
                    "best_fitness": None,
                },
            )
        except HTTPException as e:
            _set_job(job_id, status="failed", error=str(e.detail))
        except Exception as e:  # noqa: BLE001 - surface any solver error to the client
            _set_job(job_id, status="failed", error=str(e))
        finally:
            worker_db.close()

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id, "status": "running"}


@router.get("/optimize/status/{job_id}")
def optimize_status(job_id: str):
    """Return the current state of a background optimization job."""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown job id: {job_id}")
        return {"job_id": job_id, **job}