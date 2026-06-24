"""
Upload endpoints: ingest flight schedules and aircraft data.

Ingestion paths:
  - POST /api/sample          : generate synthetic Turkish domestic flight data
                                (used by the "Generate sample" button in the UI)
  - POST /api/upload/flights  : ingest a user-provided flight-schedule CSV
  - POST /api/upload/aircraft : ingest a user-provided aircraft-fleet CSV

The synthetic generator lives in services/flight_generator.py; the /sample
endpoint just exposes it via HTTP (now with multi-day support via num_days).
"""
import csv
import io
import math
from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
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

# Flight-schedule CSV: required columns. `flight_date` (YYYY-MM-DD) is an
# OPTIONAL extra column — when present, each row is placed on its own
# calendar date, enabling multi-day uploads. When absent, every flight
# falls on today's date (original single-day behavior).
REQUIRED_COLUMNS = ["flight_id", "origin", "destination", "dep_time", "arr_time"]


class SampleRequest(BaseModel):
    """Body of POST /api/sample."""
    size: str = Field("medium", pattern="^(small|medium|large)$")
    seed: Optional[int] = None
    num_days: int = Field(1, ge=1, le=120)  # per-day load * num_days = total
    clear_existing: bool = True
    # Loading new data wipes the schedule and all runs. If a published plan of
    # record exists, the request is refused (409) unless force=True, so the
    # official plan can't be destroyed by accident.
    force: bool = False


def _guard_published_plan(db, force: bool) -> None:
    """Refuse a destructive data load when a published plan would be lost."""
    if force:
        return
    published = (
        db.query(OptimizationRun)
        .filter(OptimizationRun.status == "published",
                OptimizationRun.deleted_at == None)  # noqa: E711
        .first()
    )
    if published is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A published plan exists (run {published.run_id[:8]}). Loading "
                "new data will delete it and all runs. Resend with force=true "
                "to confirm."
            ),
        )


class SampleResponse(BaseModel):
    flights_generated: int
    aircraft_generated: int
    date: str                       # start date (kept for the existing UI)
    num_days: int = 1
    start_date: Optional[str] = None
    end_date: Optional[str] = None


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
            _guard_published_plan(db, request.force)
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
        result = generate_flights(
            size=request.size, seed=request.seed, num_days=request.num_days
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

    return SampleResponse(
        flights_generated=result["flights_generated"],
        aircraft_generated=result["aircraft_generated"],
        date=result["date"],
        num_days=result.get("num_days", 1),
        start_date=result.get("start_date"),
        end_date=result.get("end_date"),
    )


def _haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between two lat/lon points."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


@router.post("/upload/flights")
async def upload_flights(file: UploadFile = File(...), force: bool = False):
    """
    Ingest a user-provided flight schedule (CSV).

    Required columns: flight_id, origin, destination, dep_time, arr_time
    (dep_time/arr_time are HH:MM). Optional column: flight_date (YYYY-MM-DD)
    — when present each row is placed on that calendar date, so the schedule
    can span multiple days; when absent all flights fall on today. Replaces
    the current flight schedule; the existing fleet and airports are kept.
    Distances are computed via Haversine from the airports table. Returns
    structured errors/warnings.
    """
    # 1. File type
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted.")

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")  # tolerate BOM
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded.")

    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []

    # 2. Schema validation
    missing = [c for c in REQUIRED_COLUMNS if c not in headers]
    if missing:
        return {
            "ok": False,
            "flights_imported": 0,
            "errors": [{"type": "missing_columns", "columns": missing}],
            "warnings": [],
        }

    has_date_col = "flight_date" in headers

    db = SessionLocal()
    try:
        from persistence.models import (
            Airport, Aircraft, Assignment, OptimizationRun,
            FlightConnection, Flight,
        )

        airports = {
            a.iata_code: (a.latitude, a.longitude)
            for a in db.query(Airport).filter(Airport.deleted_at.is_(None)).all()
        }
        aircraft_count = (
            db.query(Aircraft).filter(Aircraft.deleted_at.is_(None)).count()
        )

        rows = list(reader)
        errors = []
        warnings = []
        seen_ids = {}
        parsed = []

        for i, row in enumerate(rows):
            line = i + 2  # CSV header is line 1
            fid = (row.get("flight_id") or "").strip()
            origin = (row.get("origin") or "").strip().upper()
            dest = (row.get("destination") or "").strip().upper()
            dep_s = (row.get("dep_time") or "").strip()
            arr_s = (row.get("arr_time") or "").strip()

            if not fid:
                errors.append({"type": "missing_value", "row": line, "column": "flight_id"})

            dep_t = arr_t = None
            try:
                dep_t = datetime.strptime(dep_s, "%H:%M").time()
            except ValueError:
                errors.append({"type": "invalid_time_format", "row": line,
                               "column": "dep_time", "value": dep_s})
            try:
                arr_t = datetime.strptime(arr_s, "%H:%M").time()
            except ValueError:
                errors.append({"type": "invalid_time_format", "row": line,
                               "column": "arr_time", "value": arr_s})

            # Optional per-row calendar date (multi-day schedules).
            fdate = None
            if has_date_col:
                fdate_s = (row.get("flight_date") or "").strip()
                if fdate_s:
                    try:
                        fdate = datetime.strptime(fdate_s, "%Y-%m-%d").date()
                    except ValueError:
                        errors.append({"type": "invalid_date_format", "row": line,
                                       "column": "flight_date", "value": fdate_s})

            if origin not in airports:
                errors.append({"type": "unknown_airport", "row": line,
                               "column": "origin", "value": origin})
            if dest not in airports:
                errors.append({"type": "unknown_airport", "row": line,
                               "column": "destination", "value": dest})
            if origin and dest and origin == dest:
                errors.append({"type": "same_origin_destination", "row": line, "value": origin})

            if fid:
                seen_ids.setdefault(fid, []).append(line)

            parsed.append((fid, origin, dest, dep_t, arr_t, fdate))

        for fid, lines in seen_ids.items():
            if len(lines) > 1:
                warnings.append({"type": "duplicate_flight_id", "value": fid, "rows": lines})

        if not rows:
            errors.append({"type": "empty_file", "row": 0})

        # If anything is wrong, ingest NOTHING.
        if errors:
            return {"ok": False, "flights_imported": 0, "errors": errors, "warnings": warnings}

        # 3. Ingest. Clear flights + dependents (FK-safe), keep aircraft + airports.
        _guard_published_plan(db, force)
        db.query(Assignment).delete(synchronize_session=False)
        db.query(OptimizationRun).delete(synchronize_session=False)
        db.query(FlightConnection).delete(synchronize_session=False)
        db.query(Flight).delete(synchronize_session=False)
        db.commit()

        default_base = date.today()
        for (fid, origin, dest, dep_t, arr_t, fdate) in parsed:
            base = fdate or default_base
            dep_dt = datetime.combine(base, dep_t)
            arr_dt = datetime.combine(base, arr_t)
            if arr_dt <= dep_dt:
                arr_dt += timedelta(days=1)  # overnight flight (crosses midnight)
            lat1, lon1 = airports[origin]
            lat2, lon2 = airports[dest]
            dist = int(round(_haversine_km(lat1, lon1, lat2, lon2)))
            db.add(Flight(
                flight_id=fid,
                flight_number=fid,        # CSV has no separate number; reuse id
                origin=origin,
                destination=dest,
                scheduled_departure=dep_dt,
                scheduled_arrival=arr_dt,
                distance_km=dist,
                status="scheduled",
            ))
        db.commit()

        if aircraft_count == 0:
            warnings.append({
                "type": "no_aircraft",
                "message": "No aircraft in the system. Generate a sample first to create a fleet, then optimize.",
            })

        return {
            "ok": True,
            "flights_imported": len(parsed),
            "errors": [],
            "warnings": warnings,
            "aircraft_available": aircraft_count,
            "multi_day": has_date_col,
        }
    finally:
        db.close()


@router.post("/upload/aircraft")
async def upload_aircraft(file: UploadFile = File(...), force: bool = False):
    """
    Ingest a user-provided aircraft fleet (CSV).

    Required columns: tail_number, base_airport, available_from, maintenance_due
    (available_from is HH:MM; maintenance_due is YYYY-MM-DD, may be blank).
    Replaces the current fleet; flights and airports are kept.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted.")

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded.")

    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    required = ["tail_number", "base_airport", "available_from", "maintenance_due"]
    missing = [c for c in required if c not in headers]
    if missing:
        return {"ok": False, "aircraft_imported": 0,
                "errors": [{"type": "missing_columns", "columns": missing}], "warnings": []}

    db = SessionLocal()
    try:
        from persistence.models import Airport, Aircraft, Assignment, OptimizationRun

        airports = {
            a.iata_code for a in db.query(Airport).filter(Airport.deleted_at.is_(None)).all()
        }

        rows = list(reader)
        errors = []
        warnings = []
        seen = {}
        parsed = []

        for i, row in enumerate(rows):
            line = i + 2
            tail = (row.get("tail_number") or "").strip().upper()
            base = (row.get("base_airport") or "").strip().upper()
            avail_s = (row.get("available_from") or "").strip()
            maint_s = (row.get("maintenance_due") or "").strip()

            if not tail:
                errors.append({"type": "missing_value", "row": line, "column": "tail_number"})
            if base not in airports:
                errors.append({"type": "unknown_airport", "row": line,
                               "column": "base_airport", "value": base})

            avail_t = None
            if avail_s:
                try:
                    avail_t = datetime.strptime(avail_s, "%H:%M").time()
                except ValueError:
                    errors.append({"type": "invalid_time_format", "row": line,
                                   "column": "available_from", "value": avail_s})
            maint_d = None
            if maint_s:
                try:
                    maint_d = datetime.strptime(maint_s, "%Y-%m-%d").date()
                except ValueError:
                    errors.append({"type": "invalid_date_format", "row": line,
                                   "column": "maintenance_due", "value": maint_s})

            if tail:
                seen.setdefault(tail, []).append(line)
            parsed.append((tail, base, avail_t, maint_d))

        for tail, lines in seen.items():
            if len(lines) > 1:
                warnings.append({"type": "duplicate_tail_number", "value": tail, "rows": lines})

        if not rows:
            errors.append({"type": "empty_file", "row": 0})
        if errors:
            return {"ok": False, "aircraft_imported": 0, "errors": errors, "warnings": warnings}

        # Clear fleet + dependents (FK-safe), keep flights + airports.
        _guard_published_plan(db, force)
        db.query(Assignment).delete(synchronize_session=False)
        db.query(OptimizationRun).delete(synchronize_session=False)
        db.query(Aircraft).delete(synchronize_session=False)
        db.commit()

        base_date = date.today()
        for (tail, base, avail_t, maint_d) in parsed:
            avail_dt = datetime.combine(base_date, avail_t or datetime.min.time())
            db.add(Aircraft(
                tail_number=tail,
                aircraft_type="B737-800",
                base_airport=base,
                available_from=avail_dt,
                maintenance_due=maint_d,
                status="active",
            ))
        db.commit()

        return {"ok": True, "aircraft_imported": len(parsed),
                "errors": [], "warnings": warnings}
    finally:
        db.close()