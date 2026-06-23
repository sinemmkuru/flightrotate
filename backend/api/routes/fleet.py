"""
Fleet & Airport management endpoints (read-only in this phase).

GET /api/fleet/aircraft  -> the aircraft fleet (tail, type, base, availability,
                            maintenance due, status)
GET /api/fleet/airports  -> the airport master data (codes, name, city,
                            coordinates, min turnaround, operational flag)

This module is intentionally self-contained: it defines its own response
schemas and does not touch analytics.py, the shared optimization schemas, or
the existing GET /api/airports (which the Map view depends on). It is the home
for all fleet/airport management, so the write operations (POST/PUT/DELETE)
for full CRUD can be added here later without disturbing anything else.

All queries exclude soft-deleted rows (deleted_at IS NULL).
"""
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from persistence.database import get_db
from persistence.models import Aircraft, Airport

router = APIRouter()


class AircraftRow(BaseModel):
    tail_number: str
    aircraft_type: Optional[str] = None
    base_airport: str
    available_from: Optional[datetime] = None
    maintenance_due: Optional[date] = None
    status: Optional[str] = None


class AirportRow(BaseModel):
    iata_code: str
    icao_code: Optional[str] = None
    name: str
    city: Optional[str] = None
    latitude: float
    longitude: float
    min_turnaround_min: Optional[int] = None
    is_operational: bool


@router.get("/fleet/aircraft", response_model=list[AircraftRow])
def list_aircraft(db: Session = Depends(get_db)):
    """Return the active fleet (non-deleted), ordered by tail number."""
    rows = (
        db.query(Aircraft)
        .filter(Aircraft.deleted_at == None)  # noqa: E711
        .order_by(Aircraft.tail_number)
        .all()
    )
    return [
        AircraftRow(
            tail_number=a.tail_number,
            aircraft_type=a.aircraft_type,
            base_airport=a.base_airport,
            available_from=a.available_from,
            maintenance_due=a.maintenance_due,
            status=a.status,
        )
        for a in rows
    ]


@router.get("/fleet/airports", response_model=list[AirportRow])
def list_airports(db: Session = Depends(get_db)):
    """Return all airports (non-deleted), ordered by IATA code."""
    rows = (
        db.query(Airport)
        .filter(Airport.deleted_at == None)  # noqa: E711
        .order_by(Airport.iata_code)
        .all()
    )
    return [
        AirportRow(
            iata_code=a.iata_code,
            icao_code=a.icao_code,
            name=a.name,
            city=a.city,
            latitude=a.latitude,
            longitude=a.longitude,
            min_turnaround_min=a.min_turnaround_min,
            is_operational=bool(a.is_operational),
        )
        for a in rows
    ]