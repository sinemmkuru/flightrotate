"""
Fleet & Airport management endpoints (read + write / CRUD).

Read:
  GET    /api/fleet/aircraft          list the fleet
  GET    /api/fleet/airports          list airport master data

Write (aircraft):
  POST   /api/fleet/aircraft          create (or revive a soft-deleted tail)
  PUT    /api/fleet/aircraft/{tail}   update mutable fields
  DELETE /api/fleet/aircraft/{tail}   soft-delete (removes from active fleet)

Write (airports):
  POST   /api/fleet/airports          create (or revive a soft-deleted code)
  PUT    /api/fleet/airports/{code}   update mutable fields
  DELETE /api/fleet/airports/{code}   soft-delete, blocked if still referenced

Design notes:
  - Deletes are SOFT (set deleted_at); nothing is physically removed, matching
    the rest of the schema. A later create with the same primary key revives
    the row instead of failing.
  - Airport delete is guarded: if any non-deleted flight uses the code as
    origin/destination, or any non-deleted aircraft is based there, the delete
    is rejected (409) so optimization data never dangles.
  - Aircraft base_airport is validated against existing airports on write.
  - Self-contained: does not touch analytics.py, the shared optimization
    schemas, or the existing GET /api/airports used by the Map view.
"""
import csv
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from persistence.database import get_db
from persistence.models import Aircraft, Airport, Flight
from api.auth import require_admin

router = APIRouter()

VALID_STATUSES = {"active", "maintenance", "grounded"}

# OpenFlights reference data (~7,700 airports worldwide), shipped in the repo.
# fleet.py is at backend/api/routes/, so the backend root is three levels up.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_AIRPORTS_DAT = _BACKEND_DIR / "persistence" / "airports.dat"
_OF_NA = "\\N"  # OpenFlights missing-value marker
_airport_index: Optional[dict] = None  # lazy IATA -> reference record cache


# --------------------------------------------------------------------------
# Response + request schemas
# --------------------------------------------------------------------------
class AircraftRow(BaseModel):
    tail_number: str
    aircraft_type: Optional[str] = None
    base_airport: str
    available_from: Optional[datetime] = None
    maintenance_due: Optional[date] = None
    status: Optional[str] = None


class AircraftCreate(BaseModel):
    tail_number: str
    base_airport: str
    available_from: datetime
    aircraft_type: Optional[str] = "B737-800"
    maintenance_due: Optional[date] = None
    status: Optional[str] = "active"


class AircraftUpdate(BaseModel):
    aircraft_type: Optional[str] = None
    base_airport: Optional[str] = None
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


class AirportCreate(BaseModel):
    iata_code: str
    name: str
    latitude: float
    longitude: float
    icao_code: Optional[str] = None
    city: Optional[str] = None
    timezone: Optional[str] = "Europe/Istanbul"
    min_turnaround_min: Optional[int] = 45
    is_operational: Optional[bool] = False


class AirportUpdate(BaseModel):
    icao_code: Optional[str] = None
    name: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    min_turnaround_min: Optional[int] = None
    is_operational: Optional[bool] = None


class AirportLookup(BaseModel):
    """Reference data for an IATA code, looked up from OpenFlights (read-only)."""
    iata_code: str
    icao_code: Optional[str] = None
    name: Optional[str] = None
    city: Optional[str] = None
    latitude: float
    longitude: float


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _changes(body) -> dict:
    """Return only the fields the client actually sent (Pydantic v1/v2 safe)."""
    if hasattr(body, "model_dump"):
        return body.model_dump(exclude_unset=True)
    return body.dict(exclude_unset=True)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aircraft_row(a: Aircraft) -> AircraftRow:
    return AircraftRow(
        tail_number=a.tail_number,
        aircraft_type=a.aircraft_type,
        base_airport=a.base_airport,
        available_from=a.available_from,
        maintenance_due=a.maintenance_due,
        status=a.status,
    )


def _airport_row(a: Airport) -> AirportRow:
    return AirportRow(
        iata_code=a.iata_code,
        icao_code=a.icao_code,
        name=a.name,
        city=a.city,
        latitude=a.latitude,
        longitude=a.longitude,
        min_turnaround_min=a.min_turnaround_min,
        is_operational=bool(a.is_operational),
    )


def _require_airport(code: str, db: Session) -> Airport:
    ap = (
        db.query(Airport)
        .filter(Airport.iata_code == code, Airport.deleted_at == None)  # noqa: E711
        .first()
    )
    if ap is None:
        raise HTTPException(status_code=400, detail=f"Unknown airport '{code}'")
    return ap


def _validate_status(status: Optional[str]) -> None:
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{status}'. Allowed: {sorted(VALID_STATUSES)}",
        )


# --------------------------------------------------------------------------
# Aircraft - read
# --------------------------------------------------------------------------
@router.get("/fleet/aircraft", response_model=list[AircraftRow])
def list_aircraft(db: Session = Depends(get_db)):
    """Return the active fleet (non-deleted), ordered by tail number."""
    rows = (
        db.query(Aircraft)
        .filter(Aircraft.deleted_at == None)  # noqa: E711
        .order_by(Aircraft.tail_number)
        .all()
    )
    return [_aircraft_row(a) for a in rows]


# --------------------------------------------------------------------------
# Aircraft - write
# --------------------------------------------------------------------------
@router.post("/fleet/aircraft", response_model=AircraftRow, status_code=201)
def create_aircraft(body: AircraftCreate, db: Session = Depends(get_db),
                    _admin: str = Depends(require_admin)):
    """Create a new aircraft, or revive one previously soft-deleted."""
    tail = body.tail_number.strip().upper()
    if not tail:
        raise HTTPException(status_code=400, detail="tail_number is required")
    _validate_status(body.status)
    _require_airport(body.base_airport, db)

    existing = (
        db.query(Aircraft).filter(Aircraft.tail_number == tail).first()
    )
    if existing is not None and existing.deleted_at is None:
        raise HTTPException(status_code=409, detail=f"Aircraft '{tail}' already exists")

    if existing is not None:
        # Revive a soft-deleted tail with the new values.
        existing.deleted_at = None
        existing.aircraft_type = body.aircraft_type or "B737-800"
        existing.base_airport = body.base_airport
        existing.available_from = body.available_from
        existing.maintenance_due = body.maintenance_due
        existing.status = body.status or "active"
        db.commit()
        db.refresh(existing)
        return _aircraft_row(existing)

    ac = Aircraft(
        tail_number=tail,
        aircraft_type=body.aircraft_type or "B737-800",
        base_airport=body.base_airport,
        available_from=body.available_from,
        maintenance_due=body.maintenance_due,
        status=body.status or "active",
    )
    db.add(ac)
    db.commit()
    db.refresh(ac)
    return _aircraft_row(ac)


@router.put("/fleet/aircraft/{tail}", response_model=AircraftRow)
def update_aircraft(tail: str, body: AircraftUpdate, db: Session = Depends(get_db),
                    _admin: str = Depends(require_admin)):
    """Update mutable fields of an existing aircraft."""
    ac = (
        db.query(Aircraft)
        .filter(Aircraft.tail_number == tail, Aircraft.deleted_at == None)  # noqa: E711
        .first()
    )
    if ac is None:
        raise HTTPException(status_code=404, detail=f"Aircraft '{tail}' not found")

    changes = _changes(body)
    if "status" in changes:
        _validate_status(changes["status"])
    if "base_airport" in changes and changes["base_airport"] is not None:
        _require_airport(changes["base_airport"], db)

    for field in ("aircraft_type", "base_airport", "available_from",
                  "maintenance_due", "status"):
        if field in changes:
            setattr(ac, field, changes[field])

    db.commit()
    db.refresh(ac)
    return _aircraft_row(ac)


@router.delete("/fleet/aircraft/{tail}")
def delete_aircraft(tail: str, db: Session = Depends(get_db),
                    _admin: str = Depends(require_admin)):
    """Soft-delete an aircraft (removes it from the active fleet)."""
    ac = (
        db.query(Aircraft)
        .filter(Aircraft.tail_number == tail, Aircraft.deleted_at == None)  # noqa: E711
        .first()
    )
    if ac is None:
        raise HTTPException(status_code=404, detail=f"Aircraft '{tail}' not found")
    ac.deleted_at = _utcnow()
    db.commit()
    return {"ok": True, "tail_number": tail, "deleted": True}


# --------------------------------------------------------------------------
# Airports - reference lookup (OpenFlights), for IATA auto-fill
# --------------------------------------------------------------------------
def _clean_of(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip()
    return None if v == "" or v == _OF_NA else v


def _load_airport_index() -> dict:
    """
    Build (once, then cache) an IATA -> reference-record index from the
    OpenFlights airports.dat shipped in the repo. Columns (no header):
    id, name, city, country, iata, icao, lat, lon, ...; '\\N' marks missing.
    """
    global _airport_index
    if _airport_index is not None:
        return _airport_index

    index: dict = {}
    with open(_AIRPORTS_DAT, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 8:
                continue
            iata = (row[4] or "").strip()
            if not iata or iata == _OF_NA or len(iata) != 3:
                continue
            try:
                lat = float(row[6])
                lon = float(row[7])
            except (ValueError, IndexError):
                continue
            index[iata.upper()] = {
                "iata_code": iata.upper(),
                "icao_code": _clean_of(row[5]),
                "name": _clean_of(row[1]),
                "city": _clean_of(row[2]),
                "latitude": lat,
                "longitude": lon,
            }
    _airport_index = index
    return _airport_index


@router.get("/fleet/airport-lookup/{iata}", response_model=AirportLookup)
def airport_lookup(iata: str):
    """
    Look up an IATA code in the OpenFlights reference data and return its
    name, city, coordinates, and ICAO code, so the Add-airport form can
    auto-fill. Read-only; does not touch the database.
    """
    code = (iata or "").strip().upper()
    if len(code) != 3:
        raise HTTPException(status_code=400, detail="IATA code must be 3 letters")
    try:
        index = _load_airport_index()
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail=(
                "Reference data not found (persistence/airports.dat). "
                "Download it from OpenFlights into backend/persistence/."
            ),
        )
    rec = index.get(code)
    if rec is None:
        raise HTTPException(
            status_code=404, detail=f"IATA '{code}' not found in reference data"
        )
    return AirportLookup(**rec)


# --------------------------------------------------------------------------
# Airports - read
# --------------------------------------------------------------------------
@router.get("/fleet/airports", response_model=list[AirportRow])
def list_airports(db: Session = Depends(get_db)):
    """Return all airports (non-deleted), ordered by IATA code."""
    rows = (
        db.query(Airport)
        .filter(Airport.deleted_at == None)  # noqa: E711
        .order_by(Airport.iata_code)
        .all()
    )
    return [_airport_row(a) for a in rows]


# --------------------------------------------------------------------------
# Airports - write
# --------------------------------------------------------------------------
@router.post("/fleet/airports", response_model=AirportRow, status_code=201)
def create_airport(body: AirportCreate, db: Session = Depends(get_db),
                   _admin: str = Depends(require_admin)):
    """Create a new airport, or revive one previously soft-deleted."""
    code = body.iata_code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="iata_code is required")

    existing = db.query(Airport).filter(Airport.iata_code == code).first()
    if existing is not None and existing.deleted_at is None:
        raise HTTPException(status_code=409, detail=f"Airport '{code}' already exists")

    if existing is not None:
        existing.deleted_at = None
        existing.icao_code = body.icao_code
        existing.name = body.name
        existing.city = body.city
        existing.latitude = body.latitude
        existing.longitude = body.longitude
        existing.timezone = body.timezone or "Europe/Istanbul"
        existing.min_turnaround_min = body.min_turnaround_min or 45
        existing.is_operational = bool(body.is_operational)
        db.commit()
        db.refresh(existing)
        return _airport_row(existing)

    ap = Airport(
        iata_code=code,
        icao_code=body.icao_code,
        name=body.name,
        city=body.city,
        latitude=body.latitude,
        longitude=body.longitude,
        timezone=body.timezone or "Europe/Istanbul",
        min_turnaround_min=body.min_turnaround_min or 45,
        is_operational=bool(body.is_operational),
    )
    db.add(ap)
    db.commit()
    db.refresh(ap)
    return _airport_row(ap)


@router.put("/fleet/airports/{code}", response_model=AirportRow)
def update_airport(code: str, body: AirportUpdate, db: Session = Depends(get_db),
                   _admin: str = Depends(require_admin)):
    """Update mutable fields of an existing airport."""
    ap = (
        db.query(Airport)
        .filter(Airport.iata_code == code, Airport.deleted_at == None)  # noqa: E711
        .first()
    )
    if ap is None:
        raise HTTPException(status_code=404, detail=f"Airport '{code}' not found")

    changes = _changes(body)
    for field in ("icao_code", "name", "city", "latitude", "longitude",
                  "min_turnaround_min", "is_operational"):
        if field in changes:
            value = changes[field]
            if field == "is_operational":
                value = bool(value)
            setattr(ap, field, value)

    db.commit()
    db.refresh(ap)
    return _airport_row(ap)


@router.delete("/fleet/airports/{code}")
def delete_airport(code: str, db: Session = Depends(get_db),
                   _admin: str = Depends(require_admin)):
    """Soft-delete an airport, blocked if still referenced by data."""
    ap = (
        db.query(Airport)
        .filter(Airport.iata_code == code, Airport.deleted_at == None)  # noqa: E711
        .first()
    )
    if ap is None:
        raise HTTPException(status_code=404, detail=f"Airport '{code}' not found")

    flight_refs = (
        db.query(Flight)
        .filter(
            ((Flight.origin == code) | (Flight.destination == code)),
            Flight.deleted_at == None,  # noqa: E711
        )
        .count()
    )
    aircraft_refs = (
        db.query(Aircraft)
        .filter(Aircraft.base_airport == code, Aircraft.deleted_at == None)  # noqa: E711
        .count()
    )
    if flight_refs or aircraft_refs:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete '{code}': still referenced by "
                f"{flight_refs} flight(s) and {aircraft_refs} aircraft. "
                f"Reassign or remove those first."
            ),
        )

    ap.deleted_at = _utcnow()
    db.commit()
    return {"ok": True, "iata_code": code, "deleted": True}