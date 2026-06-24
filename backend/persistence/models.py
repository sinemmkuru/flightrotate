"""
Veritabani tablo modelleri (SQLAlchemy ORM).

ERD'deki 7 tablo:
  - Airport            : havalimani master verisi (OpenFlights'tan)
  - Aircraft           : filo
  - Flight             : ucus cizelgesi
  - OptimizationRun    : her optimizasyon calistirma kaydi
  - Assignment         : atama sonuclari (junction table)
  - FlightConnection   : Flight Connection Graph kenarlari (DAG)
  - AuditLog           : her degisikligin kaydi (who/what/when)

Soft delete: airports, aircraft, flights, optimization_runs tablolarinda
deleted_at kolonu var. Kayit fiziksel silinmez, damgalanir.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Date, Boolean, JSON, ForeignKey
)
from sqlalchemy.orm import relationship

from persistence.database import Base


def utcnow():
    """Su anki UTC zamanini dondurur (varsayilan deger olarak kullanilir)."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# AIRPORTS - Havalimani master verisi
# ---------------------------------------------------------------------------
class Airport(Base):
    __tablename__ = "airports"

    iata_code = Column(String(3), primary_key=True)   # Ornek: "IST"
    icao_code = Column(String(4))                      # Ornek: "LTFM"
    name = Column(String(120), nullable=False)
    city = Column(String(60))
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    timezone = Column(String(40), default="Europe/Istanbul")
    min_turnaround_min = Column(Integer, default=45)   # B737-800 standardi

    # is_operational: true ise sentetik ureteci bu havalimanina ucus uretir.
    # false ise sadece harita ekraninda gorunur (operasyona girmez).
    is_operational = Column(Boolean, default=False, nullable=False)

    # Soft delete
    deleted_at = Column(DateTime, nullable=True)

    # Iliskiler (bu havalimanindan kalkan/inen ucuslar, base alan ucaklar)
    flights_from = relationship(
        "Flight", foreign_keys="Flight.origin", back_populates="origin_airport"
    )
    flights_to = relationship(
        "Flight", foreign_keys="Flight.destination", back_populates="destination_airport"
    )
    based_aircraft = relationship("Aircraft", back_populates="base")


# ---------------------------------------------------------------------------
# AIRCRAFT - Filo
# ---------------------------------------------------------------------------
class Aircraft(Base):
    __tablename__ = "aircraft"

    tail_number = Column(String(10), primary_key=True)   # Ornek: "TC-JGA"
    aircraft_type = Column(String(20), default="B737-800")
    base_airport = Column(String(3), ForeignKey("airports.iata_code"), nullable=False)
    available_from = Column(DateTime, nullable=False)    # O gun kacta hazir
    maintenance_due = Column(Date, nullable=True)        # Sonraki bakim tarihi
    status = Column(String(20), default="active")        # active / maintenance / grounded

    deleted_at = Column(DateTime, nullable=True)

    base = relationship("Airport", back_populates="based_aircraft")
    assignments = relationship("Assignment", back_populates="aircraft")


# ---------------------------------------------------------------------------
# FLIGHTS - Ucus cizelgesi
# ---------------------------------------------------------------------------
class Flight(Base):
    __tablename__ = "flights"

    # flight_id: sistem ici benzersiz kimlik (flight_number'dan farkli)
    flight_id = Column(String(30), primary_key=True)
    flight_number = Column(String(10), nullable=False)   # Ornek: "TK2102"
    origin = Column(String(3), ForeignKey("airports.iata_code"), nullable=False)
    destination = Column(String(3), ForeignKey("airports.iata_code"), nullable=False)
    scheduled_departure = Column(DateTime, nullable=False)
    scheduled_arrival = Column(DateTime, nullable=False)
    distance_km = Column(Integer)                        # Haversine ile onceden hesaplanir
    status = Column(String(20), default="scheduled")     # scheduled / cancelled / delayed

    deleted_at = Column(DateTime, nullable=True)

    origin_airport = relationship(
        "Airport", foreign_keys=[origin], back_populates="flights_from"
    )
    destination_airport = relationship(
        "Airport", foreign_keys=[destination], back_populates="flights_to"
    )
    assignments = relationship("Assignment", back_populates="flight")


# ---------------------------------------------------------------------------
# OPTIMIZATION_RUNS - Her optimizasyon calistirma kaydi
# ---------------------------------------------------------------------------
class OptimizationRun(Base):
    __tablename__ = "optimization_runs"

    run_id = Column(String(40), primary_key=True)        # UUID
    created_at = Column(DateTime, default=utcnow)
    algorithm = Column(String(30), nullable=False)       # cp_sat / genetic / simulated_annealing

    # Plan-of-record status. "draft" = a candidate/scenario run; "published" =
    # the official operational plan. At most one run is published at a time
    # (enforced when publishing). Consumers (dashboard, disruption recovery,
    # past-flight locking) prefer the published run, falling back to the newest.
    status = Column(String(20), default="draft", nullable=False)

    # Objective agirliklari (toplam = 1.0)
    weight_idle = Column(Float, nullable=False)
    weight_fuel = Column(Float, nullable=False)
    weight_coverage = Column(Float, nullable=False)

    # Algoritmaya ozel parametreler (population_size, generations vb.) - esnek JSON
    parameters = Column(JSON)

    # Hesaplanan KPI'lar (denormalize - her dashboard yuklemesinde tekrar hesaplanmaz)
    coverage = Column(Float)
    idle_minutes = Column(Integer)
    fuel_kg = Column(Float)
    fuel_cost_usd = Column(Float)
    solve_time_seconds = Column(Float)
    total_flights = Column(Integer)
    assigned_flights = Column(Integer)

    deleted_at = Column(DateTime, nullable=True)

    assignments = relationship(
        "Assignment", back_populates="run", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# ASSIGNMENTS - Atama sonuclari (junction table)
# ---------------------------------------------------------------------------
class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(40), ForeignKey("optimization_runs.run_id"), nullable=False)
    flight_id = Column(String(30), ForeignKey("flights.flight_id"), nullable=False)
    tail_number = Column(String(10), ForeignKey("aircraft.tail_number"), nullable=False)

    sequence_order = Column(Integer, nullable=False)     # Ucagin gunluk rotasinda kacinci ucus
    turnaround_minutes = Column(Integer)                 # Onceki ucustan bu ucusa gecen sure
    fuel_kg = Column(Float)                              # Bu ucusun yakit tuketimi
    turnaround_warning = Column(Boolean, default=False)  # 45 dk altindaysa True

    run = relationship("OptimizationRun", back_populates="assignments")
    flight = relationship("Flight", back_populates="assignments")
    aircraft = relationship("Aircraft", back_populates="assignments")


# ---------------------------------------------------------------------------
# FLIGHT_CONNECTIONS - Flight Connection Graph kenarlari (DAG)
# ---------------------------------------------------------------------------
class FlightConnection(Base):
    __tablename__ = "flight_connections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    from_flight = Column(String(30), ForeignKey("flights.flight_id"), nullable=False)
    to_flight = Column(String(30), ForeignKey("flights.flight_id"), nullable=False)

    idle_minutes = Column(Integer, nullable=False)       # Iki ucus arasi bekleme
    fuel_cost_kg = Column(Float)                         # Bu baglantinin yakit maliyeti
    is_feasible = Column(Boolean, default=True)          # Kisitlari gecti mi


# ---------------------------------------------------------------------------
# AUDIT_LOG - Her degisikligin kaydi (who / what / when)
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    table_name = Column(String(40), nullable=False)
    record_id = Column(String(40), nullable=False)
    action = Column(String(10), nullable=False)          # INSERT / UPDATE / DELETE
    old_values = Column(JSON, nullable=True)
    new_values = Column(JSON, nullable=True)
    changed_by = Column(String(40), default="system")
    changed_at = Column(DateTime, default=utcnow)