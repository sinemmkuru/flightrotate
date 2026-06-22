"""
Pydantic schemas for the optimization API.

Pydantic models give us:
  - Automatic request validation (FastAPI uses these to reject bad input)
  - Type-safe response shapes
  - Auto-generated OpenAPI / Swagger docs at /docs

These models do NOT touch the database directly; they translate between
the JSON wire format and the internal ORM objects.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ObjectiveWeights(BaseModel):
    """Weights for the multi-objective fitness function. Must sum to ~1.0."""
    coverage: float = Field(0.50, ge=0.0, le=1.0)
    idle: float = Field(0.25, ge=0.0, le=1.0)
    fuel: float = Field(0.25, ge=0.0, le=1.0)


class GAParameters(BaseModel):
    """Tunable genetic algorithm hyperparameters."""
    population_size: int = Field(100, ge=20, le=500)
    generations: int = Field(200, ge=50, le=1000)
    tournament_size: int = Field(3, ge=2, le=10)
    elitism_count: int = Field(5, ge=0, le=20)
    mutation_rate: float = Field(0.15, ge=0.0, le=1.0)


class OptimizeRequest(BaseModel):
    """Body of POST /api/optimize.

    algorithm:
      - "genetic" : run the genetic algorithm (heuristic)
      - "cp_sat"  : run the CP-SAT exact solver
      - "auto"    : pick by instance size (small -> cp_sat, large -> genetic)
    time_limit_seconds:
      - optional CP-SAT time cap (overrides the solver default). Ignored by the
        genetic algorithm. Useful for benchmarking where CP-SAT becomes slow.
    """
    algorithm: str = Field("genetic", pattern="^(genetic|cp_sat|auto)$")
    weights: ObjectiveWeights = ObjectiveWeights()
    parameters: Optional[GAParameters] = None
    seed: Optional[int] = None
    time_limit_seconds: Optional[float] = Field(None, ge=1.0, le=600.0)


class OptimizeResponse(BaseModel):
    """Initial response after starting an optimization run."""
    run_id: str
    status: str
    message: str


class KPI(BaseModel):
    """Key performance indicators for a completed run."""
    coverage: float
    assigned_flights: int
    total_flights: int
    total_idle_minutes: int
    total_fuel_kg: float
    fuel_cost_usd: float
    solve_time_seconds: float


class RunSummary(BaseModel):
    """Summary of a single optimization run."""
    run_id: str
    created_at: datetime
    algorithm: str
    weights: ObjectiveWeights
    kpi: KPI


class AssignmentRow(BaseModel):
    """One row in a run's assignment table - a flight assigned to an aircraft."""
    flight_id: str
    flight_number: str
    origin: str
    destination: str
    scheduled_departure: datetime
    scheduled_arrival: datetime
    distance_km: int
    tail_number: str
    sequence_order: int
    turnaround_minutes: Optional[int]
    fuel_kg: float
    turnaround_warning: bool


# ---------- Comparison schemas (Day 8) ----------
class ComparisonRequest(BaseModel):
    """Body of POST /api/compare: the two run_ids to compare."""
    run_a_id: str
    run_b_id: str


class ScenarioSummary(BaseModel):
    """One side of the comparison. Mirrors a row of optimization_runs."""
    run_id: str
    created_at: str
    algorithm: str
    weight_idle: float
    weight_fuel: float
    weight_coverage: float
    total_flights: int
    assigned_flights: int
    coverage_pct: float
    idle_minutes: float
    fuel_kg: float
    fuel_cost_usd: float
    solve_time_seconds: float
    turnaround_warnings: int


class MetricDelta(BaseModel):
    """One row of the metrics table."""
    name: str
    key: str
    value_a: float
    value_b: float
    delta_absolute: float
    delta_percent: float
    better: str            # "A" | "B" | "tie"
    higher_is_better: bool
    fmt: str               # "pct" | "min" | "kg" | "usd" | "sec" | "int"


class ComparisonResult(BaseModel):
    """Full payload for POST /api/compare."""
    scenarios: dict[str, ScenarioSummary]   # {"a": ..., "b": ...}
    metrics: list[MetricDelta]
    winner: str            # "A" | "B" | "tie"
    a_wins: int
    b_wins: int
    analysis_text: str


# ---------- Airport schema (Day 9 - Map View) ----------
class AirportOut(BaseModel):
    """One airport for the map view."""
    iata_code: str
    name: str
    city: Optional[str] = None
    latitude: float
    longitude: float
    is_operational: bool