/*
  Gantt chart for the assignments table.

  Each aircraft becomes one horizontal lane. Each assigned flight is a
  block on that lane, positioned by scheduled_departure → scheduled_arrival.
  Hover shows a tooltip with route + times; click selects the flight.

  vis-timeline manages all the rendering, scrolling, and zoom interactions.
  We just hand it groups (aircraft) and items (flights) and re-create the
  timeline whenever the assignments change.

  Colors:
    - blue   : a regular leg
    - orange : the leg has a turnaround_warning (< 45 min before it)
*/

import { useEffect, useRef } from "react";
import { Timeline } from "vis-timeline/standalone";
import { DataSet } from "vis-data/standalone";

import "vis-timeline/styles/vis-timeline-graph2d.css";
import "./GanttChart.css";

function GanttChart({ assignments }) {
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

    // --- Build items (one block per flight) ---
    const items = new DataSet(
      assignments.map((a) => ({
        id: `${a.tail_number}-${a.sequence_order}`,
        group: a.tail_number,
        start: a.scheduled_departure,
        end: a.scheduled_arrival,
        content: `${a.flight_number}<br/><small>${a.origin} → ${a.destination}</small>`,
        className: a.turnaround_warning ? "flight-warning" : "flight-normal",
        title:
          `${a.flight_number}<br/>` +
          `${a.origin} → ${a.destination}<br/>` +
          `${formatTime(a.scheduled_departure)} - ${formatTime(a.scheduled_arrival)}<br/>` +
          `Distance: ${a.distance_km} km<br/>` +
          `Fuel: ${Math.round(a.fuel_kg)} kg` +
          (a.turnaround_minutes !== null
            ? `<br/>Turnaround before: ${a.turnaround_minutes} min`
            : ""),
      })),
    );

    // --- Timeline options ---
    // Fit the window to the data so the user sees the whole day at once
    const allTimes = assignments.flatMap((a) => [
      new Date(a.scheduled_departure),
      new Date(a.scheduled_arrival),
    ]);
    const minTime = new Date(Math.min(...allTimes));
    const maxTime = new Date(Math.max(...allTimes));
    // Pad both ends by 30 minutes so blocks aren't flush against the edge
    const PAD_MS = 30 * 60 * 1000;
    const windowStart = new Date(minTime.getTime() - PAD_MS);
    const windowEnd = new Date(maxTime.getTime() + PAD_MS);

    const options = {
      stack: false, // one flight per row at a time
      orientation: "top",
      zoomMin: 1000 * 60 * 30, // 30 min minimum zoom
      zoomMax: 1000 * 60 * 60 * 24 * 3, // 3 days maximum zoom
      start: windowStart,
      end: windowEnd,
      margin: { item: 6, axis: 8 },
      groupOrder: "id",
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

    // Cleanup on unmount
    return () => {
      if (timelineRef.current) {
        timelineRef.current.destroy();
        timelineRef.current = null;
      }
    };
  }, [assignments]);

  return <div ref={containerRef} className="gantt-container" />;
}

function formatTime(isoString) {
  const d = new Date(isoString);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default GanttChart;
