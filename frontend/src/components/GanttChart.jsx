/*
Gantt chart for the assignments table (multi-day capable).

Each aircraft becomes one horizontal lane. Each assigned flight is a block on
that lane, positioned by scheduled_departure -> scheduled_arrival. Hover shows
a tooltip with route + times; multi-day schedules also show the date. Clicking
a flight block opens the detail panel via the onSelectFlight callback.

Multi-day features:
  - RON (Remain-Over-Night) blocks: when the on-ground gap between two
    consecutive flights of the same aircraft exceeds the same-day idle cap
    (MAX_IDLE_MINUTES = 240 min in the graph builder), that connection is an
    overnight edge. A dim, dashed "RON" block is drawn in the gap so the
    aircraft's overnight rest at an airport is visible.
  - Day bands: alternating faint background shading per calendar day so day
    boundaries are easy to read across a week/month.
  - The zoom-out limit and initial window scale to the full data span, so a
    7- or 30-day schedule fits on screen at once.

Single-day schedules look exactly as before (no day bands, no RON blocks,
time-only tooltips).

vis-timeline manages rendering, scrolling, and zoom. We hand it groups
(aircraft) and items (flights + RON + day bands) and re-create the timeline
whenever the assignments change.

Colors:
  - blue   : a regular leg
  - orange : the leg has a turnaround_warning (< 45 min before it)
  - dim    : an overnight (RON) ground block between two legs
*/
import { useEffect, useRef } from "react";
import { Timeline } from "vis-timeline/standalone";
import { DataSet } from "vis-data/standalone";
import "vis-timeline/styles/vis-timeline-graph2d.css";
import "./GanttChart.css";

// Same-day idle cap used by the graph builder. A gap larger than this between
// two consecutive flights of one aircraft can only be an overnight (RON) edge.
const MAX_IDLE_MINUTES = 240;
const DAY_MS = 1000 * 60 * 60 * 24;

function GanttChart({ assignments, onSelectFlight }) {
  const containerRef = useRef(null);
  const timelineRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return;
    if (!assignments || assignments.length === 0) {
      // Tear down any existing timeline if assignments empty
      if (timelineRef.current) {
        timelineRef.current.destroy();
        timelineRef.current = null;
      }
      return;
    }

    // --- Build groups (one row per aircraft) ---
    const tailNumbers = Array.from(
      new Set(assignments.map((a) => a.tail_number)),
    ).sort();
    const groups = new DataSet(
      tailNumbers.map((tail) => ({
        id: tail,
        content: tail,
      })),
    );

    // --- Time span + multi-day detection ---
    const allTimes = assignments.flatMap((a) => [
      new Date(a.scheduled_departure),
      new Date(a.scheduled_arrival),
    ]);
    const minTime = new Date(Math.min(...allTimes));
    const maxTime = new Date(Math.max(...allTimes));
    const multiDay = maxTime.getTime() - minTime.getTime() > DAY_MS;

    // --- Build flight items (one block per flight) ---
    const itemList = assignments.map((a) => ({
      id: `${a.tail_number}-${a.sequence_order}`,
      group: a.tail_number,
      start: a.scheduled_departure,
      end: a.scheduled_arrival,
      content: `${a.flight_number}<br/><small>${a.origin} → ${a.destination}</small>`,
      className: a.turnaround_warning ? "flight-warning" : "flight-normal",
      title:
        `${a.flight_number}<br/>` +
        `${a.origin} → ${a.destination}<br/>` +
        `${formatRange(a.scheduled_departure, a.scheduled_arrival, multiDay)}<br/>` +
        `Distance: ${a.distance_km} km<br/>` +
        `Fuel: ${Math.round(a.fuel_kg)} kg` +
        (a.turnaround_minutes !== null && a.turnaround_minutes !== undefined
          ? `<br/>Turnaround before: ${a.turnaround_minutes} min`
          : ""),
    }));

    // --- Build RON (overnight) blocks between consecutive legs ---
    // Group each aircraft's flights, sort by departure, and for every
    // consecutive pair whose on-ground gap exceeds the same-day idle cap,
    // draw a dim block spanning the gap (the aircraft resting overnight).
    const byTail = {};
    for (const a of assignments) {
      (byTail[a.tail_number] ||= []).push(a);
    }
    for (const tail of tailNumbers) {
      const legs = byTail[tail]
        .slice()
        .sort(
          (x, y) =>
            new Date(x.scheduled_departure) - new Date(y.scheduled_departure),
        );
      for (let i = 0; i < legs.length - 1; i++) {
        const prev = legs[i];
        const next = legs[i + 1];
        const gapMin =
          (new Date(next.scheduled_departure) -
            new Date(prev.scheduled_arrival)) /
          60000;
        if (gapMin > MAX_IDLE_MINUTES) {
          const h = Math.floor(gapMin / 60);
          const m = Math.round(gapMin % 60);
          itemList.push({
            id: `ron-${tail}-${prev.sequence_order}`,
            group: tail,
            start: prev.scheduled_arrival,
            end: next.scheduled_departure,
            content: "RON",
            className: "flight-ron",
            selectable: false,
            title:
              `Overnight rest at ${prev.destination}<br/>` +
              `${formatStamp(prev.scheduled_arrival, true)} → ` +
              `${formatStamp(next.scheduled_departure, true)}<br/>` +
              `${h}h ${m}m on ground`,
          });
        }
      }
    }

    // --- Day bands: alternating faint shading per calendar day (multi-day) ---
    if (multiDay) {
      const dayCursor = new Date(minTime);
      dayCursor.setHours(0, 0, 0, 0);
      let d = 0;
      while (dayCursor < maxTime) {
        const dayStart = new Date(dayCursor);
        const dayEnd = new Date(dayCursor);
        dayEnd.setDate(dayEnd.getDate() + 1);
        itemList.push({
          id: `day-${d}`,
          start: dayStart,
          end: dayEnd,
          type: "background",
          className: d % 2 === 0 ? "day-band-even" : "day-band-odd",
        });
        dayCursor.setDate(dayCursor.getDate() + 1);
        d++;
      }
    }

    const items = new DataSet(itemList);

    // --- Timeline options ---
    // Pad both ends by 30 minutes so blocks aren't flush against the edge.
    const PAD_MS = 30 * 60 * 1000;
    const windowStart = new Date(minTime.getTime() - PAD_MS);
    const windowEnd = new Date(maxTime.getTime() + PAD_MS);
    const spanMs = windowEnd.getTime() - windowStart.getTime();

    const options = {
      stack: false, // one flight per row at a time; RON blocks fill the gaps
      orientation: "top",
      zoomMin: 1000 * 60 * 30, // 30 min minimum zoom
      // Allow zooming out to the whole schedule (>= the full span), so a
      // multi-week/month horizon fits on screen instead of being capped at 3d.
      zoomMax: Math.max(DAY_MS * 3, Math.ceil(spanMs * 1.5)),
      start: windowStart,
      end: windowEnd,
      margin: { item: 6, axis: 8 },
      groupOrder: "id",
      // Many aircraft lanes: scroll vertically instead of growing unbounded.
      verticalScroll: true,
      maxHeight: 520,
      tooltip: {
        followMouse: true,
        overflowMethod: "cap",
      },
    };

    // Destroy any previous timeline before creating a new one
    if (timelineRef.current) {
      timelineRef.current.destroy();
    }
    timelineRef.current = new Timeline(
      containerRef.current,
      items,
      groups,
      options,
    );

    // Open the flight detail panel when a flight block is clicked.
    // props.item is the clicked item's id. Flight items use the id
    // `${tail}-${seq}`, so the lookup below only matches real legs - clicks
    // on RON ("ron-...") or day-band ("day-...") items find no assignment
    // and are silently ignored, so the panel only opens for actual flights.
    timelineRef.current.on("click", (props) => {
      if (props.item == null) return;
      const a = assignments.find(
        (x) => `${x.tail_number}-${x.sequence_order}` === props.item,
      );
      if (a && onSelectFlight) onSelectFlight(a);
    });

    // Cleanup on unmount
    return () => {
      if (timelineRef.current) {
        timelineRef.current.destroy();
        timelineRef.current = null;
      }
    };
  }, [assignments, onSelectFlight]);

  return (
    <div className="gantt-wrapper">
      <div ref={containerRef} className="gantt-container" />
      <div className="gantt-legend">
        <span>
          <i className="legend-swatch legend-normal" /> Leg
        </span>
        <span>
          <i className="legend-swatch legend-warning" /> Tight turnaround
        </span>
        <span>
          <i className="legend-swatch legend-ron" /> Overnight (RON)
        </span>
      </div>
    </div>
  );
}

// "08:05" (single-day) — just the clock.
function formatClock(isoString) {
  const d = new Date(isoString);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// "Jun 23 08:05" — clock with date, for multi-day context.
function formatStamp(isoString, withDate) {
  const d = new Date(isoString);
  const clock = d.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  if (!withDate) return clock;
  const day = d.toLocaleDateString([], { month: "short", day: "numeric" });
  return `${day} ${clock}`;
}

// Departure - arrival range; includes the date(s) only when multi-day.
function formatRange(depIso, arrIso, multiDay) {
  if (!multiDay) {
    return `${formatClock(depIso)} - ${formatClock(arrIso)}`;
  }
  return `${formatStamp(depIso, true)} - ${formatStamp(arrIso, true)}`;
}

export default GanttChart;
