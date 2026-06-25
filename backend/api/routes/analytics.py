"""
Analytics endpoints: list runs, fetch a single run, fetch assignments.

These are read-only endpoints that the frontend uses to display the
dashboard, comparison view, and run history.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from typing import Optional

from persistence.database import get_db
from persistence.models import OptimizationRun, Assignment, Flight, Aircraft, AuditLog, Plan
from api.routes.plans import get_active_plan_id
from api.auth import require_admin
from api.schemas.optimization import (
    KPI, ObjectiveWeights, RunSummary, AssignmentRow,
)
from engine.cost_model import fuel_cost_usd


router = APIRouter()


def _audit(db: Session, record_id: str, old: dict, new: dict) -> None:
    """Record a plan status change in the audit log (who/what/when)."""
    db.add(AuditLog(
        table_name="optimization_runs",
        record_id=record_id,
        action="UPDATE",
        old_values=old,
        new_values=new,
        changed_by="system",  # no auth layer yet; all changes are "system"
    ))


def _run_to_summary(run: OptimizationRun) -> RunSummary:
    """Convert an OptimizationRun ORM object to a RunSummary response."""
    return RunSummary(
        run_id=run.run_id,
        created_at=run.created_at,
        algorithm=run.algorithm,
        weights=ObjectiveWeights(
            coverage=run.weight_coverage,
            idle=run.weight_idle,
            robustness=run.weight_robustness,
        ),
        kpi=KPI(
            coverage=run.coverage or 0.0,
            assigned_flights=run.assigned_flights or 0,
            total_flights=run.total_flights or 0,
            total_idle_minutes=run.idle_minutes or 0,
            total_fuel_kg=run.fuel_kg or 0.0,
            fuel_cost_usd=run.fuel_cost_usd or 0.0,
            solve_time_seconds=run.solve_time_seconds or 0.0,
        ),
        reference_time=(run.parameters or {}).get("reference_time"),
        status=run.status or "draft",
    )


@router.get("/runs", response_model=list[RunSummary])
def list_runs(db: Session = Depends(get_db)):
    """Returns all optimization runs, newest first."""
    runs = (
        db.query(OptimizationRun)
        .filter(
            OptimizationRun.deleted_at == None,  # noqa: E711
            OptimizationRun.plan_id == get_active_plan_id(db),
        )
        .order_by(OptimizationRun.created_at.desc())
        .all()
    )
    return [_run_to_summary(r) for r in runs]


@router.get("/runs/{run_id}", response_model=RunSummary)
def get_run(run_id: str, db: Session = Depends(get_db)):
    """Returns a single run by ID. 404 if not found."""
    run = (
        db.query(OptimizationRun)
        .filter(
            OptimizationRun.run_id == run_id,
            OptimizationRun.deleted_at == None,
        )
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return _run_to_summary(run)


# ---------- Plan of record (publish / unpublish) ----------
@router.get("/published-plan", response_model=Optional[RunSummary])
def get_published_plan(db: Session = Depends(get_db)):
    """The current published plan of record, or null if none is published."""
    run = (
        db.query(OptimizationRun)
        .filter(
            OptimizationRun.status == "published",
            OptimizationRun.deleted_at == None,  # noqa: E711
            OptimizationRun.plan_id == get_active_plan_id(db),
        )
        .order_by(OptimizationRun.created_at.desc())
        .first()
    )
    if run is None:
        return None

    summary = _run_to_summary(run)

    # Staleness: does the published plan still match the live schedule/fleet?
    assigns = db.query(Assignment).filter(Assignment.run_id == run.run_id).all()
    live_flights = {
        fid for (fid,) in db.query(Flight.flight_id)
        .filter(Flight.deleted_at == None).all()  # noqa: E711
    }
    live_tails = {
        t for (t,) in db.query(Aircraft.tail_number)
        .filter(Aircraft.deleted_at == None, Aircraft.status == "active").all()  # noqa: E711
    }
    missing_f = sum(1 for a in assigns if a.flight_id not in live_flights)
    missing_t = sum(1 for a in assigns if a.tail_number not in live_tails)

    parts = []
    if missing_f:
        parts.append(f"{missing_f} assigned flight(s) no longer exist")
    if missing_t:
        parts.append(f"{missing_t} assignment(s) use a removed/inactive aircraft")
    # The schedule changed after this run was optimized (e.g. a merge upload that
    # added/updated/removed flights while keeping the run).
    plan = db.query(Plan).filter(Plan.id == run.plan_id).first()
    if (plan is not None and plan.schedule_updated_at is not None
            and run.created_at is not None
            and run.created_at < plan.schedule_updated_at):
        parts.append("the schedule changed after it was optimized")

    if parts:
        summary.stale = True
        summary.stale_detail = (
            "Published plan is out of sync with the current schedule: "
            + "; ".join(parts) + ". Re-optimize and publish to refresh."
        )
    return summary


@router.post("/runs/{run_id}/publish", response_model=RunSummary)
def publish_run(run_id: str, db: Session = Depends(get_db),
                _admin: str = Depends(require_admin)):
    """
    Mark a run as the published plan of record. Any previously published run is
    demoted to draft, so at most one plan is published at a time. Audited.
    """
    run = (
        db.query(OptimizationRun)
        .filter(
            OptimizationRun.run_id == run_id,
            OptimizationRun.deleted_at == None,  # noqa: E711
        )
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    # Single-publish guarantee: demote whoever is currently published.
    for other in (
        db.query(OptimizationRun)
        .filter(
            OptimizationRun.status == "published",
            OptimizationRun.run_id != run_id,
        )
        .all()
    ):
        _audit(db, other.run_id, {"status": "published"}, {"status": "draft"})
        other.status = "draft"

    if run.status != "published":
        _audit(db, run_id, {"status": run.status}, {"status": "published"})
        run.status = "published"
    db.commit()
    db.refresh(run)
    return _run_to_summary(run)


@router.post("/runs/{run_id}/unpublish", response_model=RunSummary)
def unpublish_run(run_id: str, db: Session = Depends(get_db),
                  _admin: str = Depends(require_admin)):
    """Demote a published run back to draft (leaving no plan of record)."""
    run = (
        db.query(OptimizationRun)
        .filter(
            OptimizationRun.run_id == run_id,
            OptimizationRun.deleted_at == None,  # noqa: E711
        )
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.status == "published":
        _audit(db, run_id, {"status": "published"}, {"status": "draft"})
        run.status = "draft"
        db.commit()
        db.refresh(run)
    return _run_to_summary(run)


@router.get("/capacity-suggestion")
def capacity_suggestion(db: Session = Depends(get_db)):
    """
    Lever A: how many extra aircraft, and where, would make every scheduled
    flight in the active plan flyable — with an estimated wet-lease cost. A
    read-only what-if (it re-solves with CP-SAT but never changes the fleet).
    """
    from persistence.models import Flight, Aircraft, Airport
    from engine.capacity import suggest_capacity

    plan_id = get_active_plan_id(db)
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
        .filter(Aircraft.status == "active", Aircraft.deleted_at == None)  # noqa: E711
        .all()
    )
    if not flights or not aircraft_list:
        return {"available": False, "reason": "no flights or aircraft loaded"}

    airport_turnarounds = {
        ap.iata_code: ap.min_turnaround_min
        for ap in db.query(Airport).filter(Airport.deleted_at.is_(None)).all()
        if ap.min_turnaround_min is not None
    }
    return suggest_capacity(flights, aircraft_list, airport_turnarounds)


@router.get("/ferry-suggestion")
def ferry_suggestion(db: Session = Depends(get_db)):
    """
    Lever B: recover uncovered flights by repositioning idle aircraft on empty
    ferry legs (at fuel cost) instead of adding fleet. Read-only what-if — it
    re-solves with CP-SAT and plans ferries, but never changes anything.
    """
    from persistence.models import Flight, Aircraft, Airport
    from engine.ferry import plan_ferries

    plan_id = get_active_plan_id(db)
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
        .filter(Aircraft.status == "active", Aircraft.deleted_at == None)  # noqa: E711
        .all()
    )
    if not flights or not aircraft_list:
        return {"available": False, "reason": "no flights or aircraft loaded"}

    airports = db.query(Airport).filter(Airport.deleted_at.is_(None)).all()
    coords = {a.iata_code: (a.latitude, a.longitude) for a in airports}
    airport_turnarounds = {
        a.iata_code: a.min_turnaround_min
        for a in airports
        if a.min_turnaround_min is not None
    }
    return plan_ferries(flights, aircraft_list, coords, airport_turnarounds)


@router.get("/runs/{run_id}/unassigned")
def get_unassigned(run_id: str, db: Session = Depends(get_db)):
    """
    Decision support: the flights this run could not assign, each with a reason
    code (availability / location / capacity) and the operational lever to
    recover it. Computed at solve time and stored on the run, so it is a faithful
    snapshot of why coverage fell short for the fleet as it stood then.
    """
    run = (
        db.query(OptimizationRun)
        .filter(
            OptimizationRun.run_id == run_id,
            OptimizationRun.deleted_at == None,  # noqa: E711
        )
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    params = run.parameters or {}
    return {
        "summary": params.get("unassigned_summary", {"total": 0, "by_reason": {}}),
        "flights": params.get("unassigned", []),
    }


@router.get("/runs/{run_id}/assignments", response_model=list[AssignmentRow])
def get_assignments(run_id: str, db: Session = Depends(get_db)):
    """
    Returns all flight assignments for a given run, joined with flight
    details. Used by the Dashboard's Gantt chart.
    """
    # Verify the run exists
    run = (
        db.query(OptimizationRun)
        .filter(OptimizationRun.run_id == run_id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    # Join assignments with flight details
    rows = (
        db.query(Assignment, Flight)
        .join(Flight, Assignment.flight_id == Flight.flight_id)
        .filter(Assignment.run_id == run_id)
        .order_by(Assignment.tail_number, Assignment.sequence_order)
        .all()
    )

    return [
        AssignmentRow(
            flight_id=f.flight_id,
            flight_number=f.flight_number,
            origin=f.origin,
            destination=f.destination,
            scheduled_departure=f.scheduled_departure,
            scheduled_arrival=f.scheduled_arrival,
            distance_km=f.distance_km or 0,
            tail_number=a.tail_number,
            sequence_order=a.sequence_order,
            turnaround_minutes=a.turnaround_minutes,
            fuel_kg=a.fuel_kg or 0.0,
            turnaround_warning=a.turnaround_warning or False,
        )
        for a, f in rows
    ]
    # ---------- Compare endpoint (Day 8) ----------
from fastapi import HTTPException
from api.schemas.optimization import (
    ComparisonRequest,
    ComparisonResult,
    ScenarioSummary,
    MetricDelta,
)


def _scenario_summary(run, warnings: int) -> ScenarioSummary:
    """Pack an OptimizationRun row into the schema the frontend wants."""
    coverage_pct = (run.coverage or 0.0) * 100.0
    return ScenarioSummary(
        run_id=run.run_id,
        created_at=run.created_at.isoformat() if run.created_at else "",
        algorithm=run.algorithm or "genetic",
        weight_idle=run.weight_idle,
        weight_robustness=run.weight_robustness,
        weight_coverage=run.weight_coverage,
        total_flights=run.total_flights or 0,
        assigned_flights=run.assigned_flights or 0,
        coverage_pct=round(coverage_pct, 1),
        idle_minutes=round(run.idle_minutes or 0, 1),
        fuel_kg=round(run.fuel_kg or 0, 1),
        fuel_cost_usd=round(run.fuel_cost_usd or 0, 2),
        solve_time_seconds=round(run.solve_time_seconds or 0, 2),
        turnaround_warnings=warnings,
    )


def _metric(name, key, a, b, higher_is_better, fmt) -> MetricDelta:
    delta_abs = b - a
    delta_pct = (delta_abs / a * 100.0) if a else 0.0
    if a == b:
        better = "tie"
    elif higher_is_better:
        better = "B" if b > a else "A"
    else:
        better = "B" if b < a else "A"
    return MetricDelta(
        name=name, key=key,
        value_a=round(a, 2), value_b=round(b, 2),
        delta_absolute=round(delta_abs, 2),
        delta_percent=round(delta_pct, 1),
        better=better,
        higher_is_better=higher_is_better,
        fmt=fmt,
    )


def _analysis(a: ScenarioSummary, b: ScenarioSummary, metrics, winner: str) -> str:
    if winner == "tie":
        return ("Both scenarios produce comparable results across the key "
                "metrics. Choosing between them is largely a stylistic preference.")
    by_key = {m.key: m for m in metrics}
    parts = [f"Scenario {winner} wins on the majority of metrics."]
    idle = by_key.get("idle_minutes")
    fuel = by_key.get("fuel_kg")
    cost = by_key.get("fuel_cost_usd")
    cov = by_key.get("coverage_pct")
    if idle and idle.better == winner:
        parts.append(f"Idle time is {abs(idle.delta_percent):.0f}% lower.")
    if fuel and fuel.better == winner:
        s = f"Fuel burn drops {abs(fuel.delta_percent):.0f}%"
        if cost and cost.better == winner:
            s += f" (about ${abs(cost.delta_absolute):,.0f} saved)"
        parts.append(s + ".")
    if cov and cov.better != winner and abs(cov.delta_absolute) > 0.05:
        parts.append(
            f"Coverage trade-off: {abs(cov.delta_absolute):.1f} percentage points lower."
        )
    return " ".join(parts)


@router.post("/compare", response_model=ComparisonResult)
def compare_runs(req: ComparisonRequest, db: Session = Depends(get_db)):
    """Compare two optimization runs side-by-side."""
    from persistence.models import OptimizationRun, Assignment

    def _load(run_id: str):
        run = (
            db.query(OptimizationRun)
            .filter(
                OptimizationRun.run_id == run_id,
                OptimizationRun.deleted_at.is_(None),
            )
            .first()
        )
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return run

    run_a = _load(req.run_a_id)
    run_b = _load(req.run_b_id)

    def _warn_count(rid: str) -> int:
        return (
            db.query(Assignment)
            .filter(
                Assignment.run_id == rid,
                Assignment.turnaround_warning == True,  # noqa: E712
            )
            .count()
        )

    a = _scenario_summary(run_a, _warn_count(run_a.run_id))
    b = _scenario_summary(run_b, _warn_count(run_b.run_id))

    metrics = [
        _metric("Coverage", "coverage_pct", a.coverage_pct, b.coverage_pct, True, "pct"),
        _metric("Assigned flights", "assigned_flights", a.assigned_flights, b.assigned_flights, True, "int"),
        _metric("Idle time", "idle_minutes", a.idle_minutes, b.idle_minutes, False, "min"),
        _metric("Fuel burn", "fuel_kg", a.fuel_kg, b.fuel_kg, False, "kg"),
        _metric("Fuel cost", "fuel_cost_usd", a.fuel_cost_usd, b.fuel_cost_usd, False, "usd"),
        _metric("Turnaround warnings", "turnaround_warnings", a.turnaround_warnings, b.turnaround_warnings, False, "int"),
        _metric("Solve time", "solve_time_seconds", a.solve_time_seconds, b.solve_time_seconds, False, "sec"),
    ]

    a_wins = sum(1 for m in metrics if m.better == "A")
    b_wins = sum(1 for m in metrics if m.better == "B")
    winner = "A" if a_wins > b_wins else "B" if b_wins > a_wins else "tie"

    return ComparisonResult(
        scenarios={"a": a, "b": b},
        metrics=metrics,
        winner=winner,
        a_wins=a_wins,
        b_wins=b_wins,
        analysis_text=_analysis(a, b, metrics, winner),
    )

    # ---------- Airports endpoint (Day 9 - Map View) ----------
from api.schemas.optimization import AirportOut


@router.get("/airports", response_model=list[AirportOut])
def list_airports(db: Session = Depends(get_db)):
    """All non-deleted airports for the map view."""
    from persistence.models import Airport

    airports = (
        db.query(Airport)
        .filter(Airport.deleted_at.is_(None))
        .order_by(Airport.iata_code)
        .all()
    )
    return [
        AirportOut(
            iata_code=a.iata_code,
            name=a.name,
            city=a.city,
            latitude=a.latitude,
            longitude=a.longitude,
            is_operational=bool(a.is_operational),
        )
        for a in airports
    ]

    # ---------- Data status (for UI gating) ----------
@router.get("/status")
def data_status(db: Session = Depends(get_db)):
    """Quick counts so the UI can tell whether there is data to optimize."""
    from persistence.models import Flight, Aircraft, Airport
    flights = (
        db.query(Flight)
        .filter(Flight.deleted_at.is_(None), Flight.plan_id == get_active_plan_id(db))
        .count()
    )
    aircraft = db.query(Aircraft).filter(Aircraft.deleted_at.is_(None)).count()
    airports = db.query(Airport).filter(Airport.deleted_at.is_(None)).count()
    return {"flights": flights, "aircraft": aircraft, "airports": airports}

    # ---------- Naive baseline (Day 11) ----------
@router.get("/baseline")
def get_baseline(db: Session = Depends(get_db)):
    """
    KPIs for a deterministic naive greedy baseline on the CURRENT data, so the
    dashboard can show "% improvement vs naive". Same evaluate_solution +
    fuel_cost_usd as the optimizer -> deltas are apples-to-apples.
    """
    from persistence.models import Flight, Aircraft
    from engine.baseline import compute_baseline_kpis

    flights = (
        db.query(Flight)
        .filter(
            Flight.status == "scheduled", Flight.deleted_at == None,  # noqa: E711
            Flight.plan_id == get_active_plan_id(db),
        )
        .all()
    )
    aircraft_list = (
        db.query(Aircraft)
        .filter(Aircraft.status == "active", Aircraft.deleted_at == None)  # noqa: E711
        .all()
    )
    if not flights or not aircraft_list:
        return {"available": False, "reason": "no flights or aircraft loaded"}

    from persistence.models import Airport
    airport_turnarounds = {
        ap.iata_code: ap.min_turnaround_min
        for ap in db.query(Airport).filter(Airport.deleted_at.is_(None)).all()
        if ap.min_turnaround_min is not None
    }
    # Hold the baseline to the same hard constraint as the optimizer: each
    # aircraft starts at its base, so an airport can only originate as many
    # rotations as it has aircraft based there. Otherwise the "% vs naive"
    # comparison would be unfair (the naive plan could teleport aircraft).
    aircraft_starts = {a.tail_number: a.base_airport for a in aircraft_list}
    kpis = compute_baseline_kpis(
        flights, aircraft_list, airport_turnarounds, aircraft_starts
    )
    kpis["available"] = True
    return kpis

    # ---------- Disruption / recovery ----------
from fastapi import HTTPException
from pydantic import BaseModel
from typing import Optional as _Optional


class DisruptRequest(BaseModel):
    type: str                              # "ground_aircraft" | "cancel" | "delay"
    flight_id: _Optional[str] = None       # required for "cancel" and "delay"
    tail_number: _Optional[str] = None     # required for "ground_aircraft"
    delay_minutes: _Optional[int] = None   # required for "delay"
    weights: _Optional[dict] = None


@router.post("/disrupt")
def disrupt(req: DisruptRequest, db: Session = Depends(get_db),
            _admin: str = Depends(require_admin)):
    """
    Apply a disruption (aircraft AOG, flight cancellation, or flight delay),
    re-optimize with CP-SAT, and return a before/after impact report. Reads the
    live schedule but never mutates the database. A "delay" also reports the
    reactionary delay that would cascade if the current plan were flown as-is.
    """
    from persistence.models import Flight, Aircraft, OptimizationRun, Assignment
    from engine.disruption import run_disruption

    flights = (
        db.query(Flight)
        .filter(
            Flight.status == "scheduled", Flight.deleted_at == None,  # noqa: E711
            Flight.plan_id == get_active_plan_id(db),
        )
        .all()
    )
    aircraft_list = (
        db.query(Aircraft)
        .filter(Aircraft.status == "active", Aircraft.deleted_at == None)  # noqa: E711
        .all()
    )
    if not flights or not aircraft_list:
        raise HTTPException(status_code=400, detail="No flights or aircraft loaded.")

    from persistence.models import Airport
    airport_turnarounds = {
        ap.iata_code: ap.min_turnaround_min
        for ap in db.query(Airport).filter(Airport.deleted_at.is_(None)).all()
        if ap.min_turnaround_min is not None
    }

    # For a delay we propagate along the plan the user is actually operating:
    # the latest optimization run's assignment. (No run yet -> run_disruption
    # falls back to a fresh solve.)
    plan_solution = None
    if req.type == "delay":
        # Propagate along the operating plan: the published plan of record if
        # one exists, otherwise the most recent run.
        latest = (
            db.query(OptimizationRun)
            .filter(
                OptimizationRun.deleted_at.is_(None),
                OptimizationRun.plan_id == get_active_plan_id(db),
            )
            .order_by(
                (OptimizationRun.status == "published").desc(),
                OptimizationRun.created_at.desc(),
            )
            .first()
        )
        if latest is not None:
            rows = (
                db.query(Assignment)
                .filter(Assignment.run_id == latest.run_id)
                .all()
            )
            plan_solution = {a.flight_id: a.tail_number for a in rows}

    try:
        return run_disruption(
            flights, aircraft_list,
            dtype=req.type, flight_id=req.flight_id,
            tail_number=req.tail_number, weights=req.weights,
            airport_turnarounds=airport_turnarounds,
            delay_minutes=req.delay_minutes, plan_solution=plan_solution,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))