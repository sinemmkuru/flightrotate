"""
Upload endpoints: ingest flight schedules and aircraft data.

For Phase 1 we expose two ingestion paths:
  - POST /api/sample : generate synthetic Turkish domestic flight data
                       (used by the "Generate sample" button in the UI)
  - POST /api/upload : ingest a user-provided CSV (added in Day 6-7
                       when frontend wiring is needed)

The synthetic generator already exists in services/flight_generator.py;
this endpoint just exposes it via HTTP.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.flight_generator import generate_flights
from persistence.database import SessionLocal
from persistence.models import (
    Flight,
    Aircraft,
    Assignment,
    OptimizationRun,
    FlightConnection,
)


router = APIRouter()


class SampleRequest(BaseModel):
    """Body of POST /api/sample."""
    size: str = Field("medium", pattern="^(small|medium|large)$")
    seed: Optional[int] = None
    clear_existing: bool = True


class SampleResponse(BaseModel):
    flights_generated: int
    aircraft_generated: int
    date: str


@router.post("/sample", response_model=SampleResponse)
def generate_sample(request: SampleRequest):
    """
    Generates a synthetic flight schedule and aircraft fleet.
    If clear_existing is True (default), wipes flights and aircraft before
    generating new ones. Airports are left untouched.
    """
    if request.clear_existing:
        db = SessionLocal()
        try:
            # FK-safe delete order: children before parents.
            # SQLite's foreign_keys=ON pragma rejects deletes that would
            # orphan referencing rows, so assignments and runs go first.
            db.query(Assignment).delete()
            db.query(OptimizationRun).delete()
            db.query(FlightConnection).delete()
            db.query(Flight).delete()
            db.query(Aircraft).delete()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    try:
        result = generate_flights(size=request.size, seed=request.seed)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

    return SampleResponse(
        flights_generated=result["flights_generated"],
        aircraft_generated=result["aircraft_generated"],
        date=result["date"],
    )