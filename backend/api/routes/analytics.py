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