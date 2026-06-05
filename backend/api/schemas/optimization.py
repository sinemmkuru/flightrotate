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
    """Body of POST /api/optimize."""
    algorithm: str = Field("genetic", pattern="^(genetic|cp_sat)$")
    weights: ObjectiveWeights = ObjectiveWeights()
    parameters: Optional[GAParameters] = None
    seed: Optional[int] = None


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