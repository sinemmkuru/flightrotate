"""
Plan (schedule) management endpoints.

A Plan is a named schedule/horizon that owns its own flights, fleet and
optimization runs. Multiple plans coexist (e.g. "June" and "July"); exactly one
is active at a time, and every other endpoint scopes its data to the active
plan via get_active_plan_id(). Switching plans is a server-side action (this is
a single-user prototype); a multi-user deployment would scope per session.

Creating a plan makes a new EMPTY active plan — the user then generates or
uploads data into it, which (being scoped) never touches the other plans.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from persistence.database import get_db
from persistence.models import Plan, Flight, Aircraft, OptimizationRun, utcnow
from api.auth import require_admin

router = APIRouter()


# --------------------------------------------------------------------------
# Active-plan helpers (imported by the other route modules)
# --------------------------------------------------------------------------
def get_active_plan(db: Session) -> Plan:
    """
    The active plan. Self-healing: if none is flagged active, activate the most
    recent plan; if there are no plans at all, create a default one.
    """
    plan = (
        db.query(Plan)
        .filter(Plan.is_active == True, Plan.deleted_at == None)  # noqa: E712,E711
        .first()
    )
    if plan is not None:
        return plan

    plan = (
        db.query(Plan)
        .filter(Plan.deleted_at == None)  # noqa: E711
        .order_by(Plan.created_at.desc())
        .first()
    )
    if plan is not None:
        plan.is_active = True
        db.commit()
        return plan

    plan = Plan(name="Plan 1", is_active=True)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def get_active_plan_id(db: Session) -> int:
    return get_active_plan(db).id


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class PlanOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    is_active: bool
    flights: int
    aircraft: int
    runs: int


class PlanCreate(BaseModel):
    name: str


class PlanUpdate(BaseModel):
    name: str


def _to_out(db: Session, plan: Plan) -> PlanOut:
    flights = (
        db.query(Flight)
        .filter(Flight.plan_id == plan.id, Flight.deleted_at == None)  # noqa: E711
        .count()
    )
    # Fleet is shared across plans (one airline, one fleet), so this is global.
    aircraft = (
        db.query(Aircraft)
        .filter(Aircraft.deleted_at == None)  # noqa: E711
        .count()
    )
    runs = (
        db.query(OptimizationRun)
        .filter(OptimizationRun.plan_id == plan.id,
                OptimizationRun.deleted_at == None)  # noqa: E711
        .count()
    )
    return PlanOut(
        id=plan.id, name=plan.name, created_at=plan.created_at,
        is_active=bool(plan.is_active), flights=flights,
        aircraft=aircraft, runs=runs,
    )


def _deactivate_all(db: Session) -> None:
    db.query(Plan).filter(Plan.is_active == True).update(  # noqa: E712
        {"is_active": False}
    )


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@router.get("/plans", response_model=list[PlanOut])
def list_plans(db: Session = Depends(get_db)):
    """All plans, newest first, with flight/aircraft/run counts."""
    get_active_plan(db)  # ensure one exists / is active
    plans = (
        db.query(Plan)
        .filter(Plan.deleted_at == None)  # noqa: E711
        .order_by(Plan.created_at.desc())
        .all()
    )
    return [_to_out(db, p) for p in plans]


@router.get("/plans/active", response_model=PlanOut)
def active_plan(db: Session = Depends(get_db)):
    """The currently active plan."""
    return _to_out(db, get_active_plan(db))


@router.post("/plans", response_model=PlanOut, status_code=201)
def create_plan(body: PlanCreate, db: Session = Depends(get_db),
                _admin: str = Depends(require_admin)):
    """Create a new EMPTY plan and make it active."""
    name = body.name.strip() or "Untitled plan"
    _deactivate_all(db)
    plan = Plan(name=name, is_active=True, created_at=utcnow())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _to_out(db, plan)


@router.post("/plans/{plan_id}/activate", response_model=PlanOut)
def activate_plan(plan_id: int, db: Session = Depends(get_db),
                  _admin: str = Depends(require_admin)):
    """Make a plan the active one (deactivating any other)."""
    plan = (
        db.query(Plan)
        .filter(Plan.id == plan_id, Plan.deleted_at == None)  # noqa: E711
        .first()
    )
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
    _deactivate_all(db)
    plan.is_active = True
    db.commit()
    db.refresh(plan)
    return _to_out(db, plan)


@router.put("/plans/{plan_id}", response_model=PlanOut)
def rename_plan(plan_id: int, body: PlanUpdate, db: Session = Depends(get_db),
                _admin: str = Depends(require_admin)):
    """Rename a plan."""
    plan = (
        db.query(Plan)
        .filter(Plan.id == plan_id, Plan.deleted_at == None)  # noqa: E711
        .first()
    )
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
    plan.name = body.name.strip() or plan.name
    db.commit()
    db.refresh(plan)
    return _to_out(db, plan)


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: int, db: Session = Depends(get_db),
                _admin: str = Depends(require_admin)):
    """
    Soft-delete a plan. Its data stays in the tables but is no longer reachable
    (queries scope to the active plan). If the deleted plan was active, another
    plan is activated (or a fresh default created), so there is always one.
    """
    plan = (
        db.query(Plan)
        .filter(Plan.id == plan_id, Plan.deleted_at == None)  # noqa: E711
        .first()
    )
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")

    plan.deleted_at = utcnow()
    plan.is_active = False
    db.commit()
    # Guarantee an active plan remains.
    get_active_plan(db)
    return {"ok": True, "id": plan_id, "deleted": True}
