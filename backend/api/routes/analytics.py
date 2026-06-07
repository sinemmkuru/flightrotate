"""
Analytics endpoints: list runs, fetch a single run, fetch assignments.

These are read-only endpoints that the frontend uses to display the
dashboard, comparison view, and run history.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from persistence.database import get_db
from persistence.models import OptimizationRun, Assignment, Flight
from api.schemas.optimization import (
    KPI, ObjectiveWeights, RunSummary, AssignmentRow,
)
from engine.cost_model import fuel_cost_usd


router = APIRouter()


def _run_to_summary(run: OptimizationRun) -> RunSummary:
    """Convert an OptimizationRun ORM object to a RunSummary response."""
    return RunSummary(
        run_id=run.run_id,
        created_at=run.created_at,
        algorithm=run.algorithm,
        weights=ObjectiveWeights(
            coverage=run.weight_coverage,
            idle=run.weight_idle,
            fuel=run.weight_fuel,
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
    )


@router.get("/runs", response_model=list[RunSummary])
def list_runs(db: Session = Depends(get_db)):
    """Returns all optimization runs, newest first."""
    runs = (
        db.query(OptimizationRun)
        .filter(OptimizationRun.deleted_at == None)
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
        weight_fuel=run.weight_fuel,
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