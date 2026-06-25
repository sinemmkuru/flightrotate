"""
Report / export endpoints: download a run's results as CSV or PDF.

GET /api/runs/{run_id}/export.csv
    Machine-readable assignment table (one row per assigned flight),
    including a derived CO2 column. Useful for offline analysis or feeding
    another tool.

GET /api/runs/{run_id}/export.pdf
    Human-readable one-document report: run metadata, a KPI summary, and the
    full assignment table. The PDF is generated with reportlab (pure Python).

Both reuse exactly the same data the dashboard shows: the run's stored KPIs
and its assignments joined to flight details. CO2 is derived from fuel with
the standard ICAO Jet A-1 factor (3.16 kg CO2 per kg fuel), matching the
frontend emissions helper.

This module is intentionally self-contained and read-only; it does not modify
any data. reportlab is imported lazily inside the PDF handler so the API (and
the CSV export) still works even if reportlab is not installed.
"""
import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from persistence.database import get_db
from persistence.models import OptimizationRun, Assignment, Flight

router = APIRouter()

# Standard ICAO Jet A-1 combustion factor: kg CO2 produced per kg fuel burned.
CO2_PER_KG_FUEL = 3.16


def _load_run(run_id: str, db: Session) -> OptimizationRun:
    """Fetch a non-deleted run or raise 404."""
    run = (
        db.query(OptimizationRun)
        .filter(
            OptimizationRun.run_id == run_id,
            OptimizationRun.deleted_at == None,  # noqa: E711
        )
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run


def _load_rows(run_id: str, db: Session):
    """Assignments for a run, joined with flight details, in rotation order."""
    return (
        db.query(Assignment, Flight)
        .join(Flight, Assignment.flight_id == Flight.flight_id)
        .filter(Assignment.run_id == run_id)
        .order_by(Assignment.tail_number, Assignment.sequence_order)
        .all()
    )


def _fmt_dt(dt) -> str:
    """Compact, sortable timestamp; empty string for None."""
    if not dt:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M")


def _short(run_id: str) -> str:
    return run_id[:8]


@router.get("/runs/{run_id}/export.csv")
def export_run_csv(run_id: str, db: Session = Depends(get_db)):
    """Download the run's assignment table as CSV (with a derived CO2 column)."""
    _load_run(run_id, db)
    rows = _load_rows(run_id, db)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "tail_number",
        "sequence_order",
        "flight_number",
        "origin",
        "destination",
        "scheduled_departure",
        "scheduled_arrival",
        "distance_km",
        "turnaround_minutes",
        "turnaround_warning",
        "fuel_kg",
        "co2_kg",
    ])
    for a, f in rows:
        fuel = a.fuel_kg or 0.0
        writer.writerow([
            a.tail_number,
            a.sequence_order,
            f.flight_number,
            f.origin,
            f.destination,
            _fmt_dt(f.scheduled_departure),
            _fmt_dt(f.scheduled_arrival),
            f.distance_km or 0,
            a.turnaround_minutes if a.turnaround_minutes is not None else "",
            bool(a.turnaround_warning),
            round(fuel, 1),
            round(fuel * CO2_PER_KG_FUEL, 1),
        ])

    fname = f"flightrotate_{_short(run_id)}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/runs/{run_id}/export.pdf")
def export_run_pdf(run_id: str, db: Session = Depends(get_db)):
    """Download a human-readable PDF report: metadata + KPI summary + table."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import mm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, LongTable,
        )
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail=(
                "PDF export needs reportlab. Install it in the backend venv: "
                "pip install reportlab"
            ),
        )

    run = _load_run(run_id, db)
    rows = _load_rows(run_id, db)

    # --- Derived figures ---
    total_fuel = run.fuel_kg or 0.0
    total_co2_t = total_fuel * CO2_PER_KG_FUEL / 1000.0  # tonnes
    coverage_pct = (run.coverage or 0.0) * 100.0

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontSize=18, spaceAfter=4,
    )
    sub_style = ParagraphStyle(
        "Sub", parent=styles["Normal"], fontSize=9, textColor=colors.grey,
    )
    h2_style = ParagraphStyle(
        "H2", parent=styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4,
    )

    elements = []
    elements.append(Paragraph("FlightRotate — Optimization Report", title_style))
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    elements.append(Paragraph(
        f"Run {_short(run.run_id)} &nbsp;·&nbsp; "
        f"{(run.algorithm or '').upper()} &nbsp;·&nbsp; "
        f"created {_fmt_dt(run.created_at)} &nbsp;·&nbsp; "
        f"generated {generated}",
        sub_style,
    ))
    elements.append(Spacer(1, 6 * mm))

    # --- KPI summary table ---
    elements.append(Paragraph("Key results", h2_style))
    weights = (
        f"coverage {run.weight_coverage:.2f} / "
        f"idle {run.weight_idle:.2f} / "
        f"robustness {run.weight_robustness:.2f}"
    )
    kpi_data = [
        ["Metric", "Value"],
        ["Coverage", f"{coverage_pct:.1f}%"],
        ["Assigned flights", f"{run.assigned_flights or 0} / {run.total_flights or 0}"],
        ["Total idle", f"{(run.idle_minutes or 0):,} min"],
        ["Total fuel", f"{total_fuel:,.0f} kg"],
        ["Fuel cost", f"${(run.fuel_cost_usd or 0.0):,.0f}"],
        ["CO2 emissions", f"{total_co2_t:,.1f} t"],
        ["Solve time", f"{(run.solve_time_seconds or 0.0):.1f} s"],
        ["Objective weights", weights],
    ]
    kpi_table = Table(kpi_data, colWidths=[55 * mm, 90 * mm])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(kpi_table)

    # --- Assignment table ---
    elements.append(Paragraph(f"Assignments ({len(rows)})", h2_style))
    header = [
        "Tail", "Seq", "Flight", "Route", "Departure", "Arrival",
        "Turn (min)", "Fuel (kg)", "CO2 (kg)",
    ]
    table_data = [header]
    for a, f in rows:
        fuel = a.fuel_kg or 0.0
        turn = a.turnaround_minutes if a.turnaround_minutes is not None else "—"
        table_data.append([
            a.tail_number,
            str(a.sequence_order),
            f.flight_number,
            f"{f.origin}→{f.destination}",
            _fmt_dt(f.scheduled_departure),
            _fmt_dt(f.scheduled_arrival),
            str(turn),
            f"{fuel:,.0f}",
            f"{fuel * CO2_PER_KG_FUEL:,.0f}",
        ])

    col_widths = [
        20 * mm, 12 * mm, 22 * mm, 26 * mm, 32 * mm, 32 * mm,
        18 * mm, 22 * mm, 22 * mm,
    ]
    assign_table = LongTable(table_data, colWidths=col_widths, repeatRows=1)

    # Highlight tight-turnaround rows in amber.
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e5e7eb")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ALIGN", (1, 1), (1, -1), "CENTER"),
        ("ALIGN", (6, 1), (8, -1), "RIGHT"),
    ]
    for i, (a, f) in enumerate(rows, start=1):
        if a.turnaround_warning:
            style_cmds.append(
                ("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fde68a"))
            )
    assign_table.setStyle(TableStyle(style_cmds))
    elements.append(assign_table)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"FlightRotate report {_short(run_id)}",
    )
    doc.build(elements)
    pdf_bytes = buf.getvalue()

    fname = f"flightrotate_{_short(run_id)}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )