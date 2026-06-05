"""
FastAPI application entry point for FlightRotate.

This module:
  - Creates the FastAPI app
  - Registers CORS so the React frontend (port 5173) can call us (port 8000)
  - Mounts the route modules (upload, optimize, analytics)
  - Provides a root health-check endpoint

Run from backend folder:
    uvicorn api.main:app --reload --port 8000

Interactive API docs are then available at:
    http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import upload, optimize, analytics


app = FastAPI(
    title="FlightRotate API",
    description="Flight Assignment and Aircraft Rotation Optimization System",
    version="0.1.0",
)


# CORS: allow the React dev server (Vite default port 5173) to call this API.
# In production this list would be tightened to specific origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Mount the route modules
app.include_router(upload.router, prefix="/api", tags=["upload"])
app.include_router(optimize.router, prefix="/api", tags=["optimize"])
app.include_router(analytics.router, prefix="/api", tags=["analytics"])


@app.get("/")
def root():
    """Health check endpoint - useful to verify the server is up."""
    return {
        "service": "FlightRotate API",
        "version": "0.1.0",
        "status": "ok",
    }