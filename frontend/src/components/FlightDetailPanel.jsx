/*
  Flight Detail Panel - a slide-in drawer shown when a flight block in the
  Gantt is clicked. Richer than a tooltip; stays open alongside the Gantt.

  The key feature is rotation context: the preceding and following leg of the
  SAME aircraft (found via tail_number + sequence_order). This answers "why is
  this aircraft here". The "Why this rotation?" button generates a factual,
  data-grounded explanation of the chaining / turnaround feasibility - it does
  NOT fabricate the optimizer's internals.
*/

import { useState } from "react";
import "./FlightDetailPanel.css";

function fmt(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function durationLabel(depIso, arrIso) {
  const dep = new Date(depIso);
  const arr = new Date(arrIso);
  let mins = Math.round((arr - dep) / 60000);
  if (mins < 0) mins += 1440;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return h > 0 ? `${h}h ${m}min` : `${m}min`;
}

function buildWhy(flight, prev, next) {
  const dep = fmt(flight.scheduled_departure);
  const arr = fmt(flight.scheduled_arrival);
  const parts = [];

  if (!prev) {
    parts.push(
      `${flight.flight_number} is the first leg of ${flight.tail_number}'s rotation, starting from ${flight.origin} at ${dep}.`,
    );
  } else {
    parts.push(
      `${flight.tail_number} arrived at ${flight.origin} on ${prev.flight_number} ` +
        `(${prev.origin}→${prev.destination}) at ${fmt(prev.scheduled_arrival)}. ` +
        `This leg departs ${flight.origin} at ${dep}` +
        (flight.turnaround_minutes != null
          ? `, a ${flight.turnaround_minutes}-minute turnaround`
          : "") +
        `. The connection is feasible, so the same aircraft flies it — chaining the ` +
        `legs keeps it productive instead of sitting idle.`,
    );
    if (flight.turnaround_warning) {
      parts.push(
        `The ${flight.turnaround_minutes}-minute turnaround is tight (below the comfortable buffer), so it is flagged for attention.`,
      );
    }
  }

  if (next) {
    parts.push(
      `After landing at ${flight.destination} at ${arr}, the aircraft continues on ` +
        `${next.flight_number} (${next.origin}→${next.destination}) at ${fmt(next.scheduled_departure)}.`,
    );
  } else {
    parts.push(
      `This is the last leg of the rotation; the aircraft finishes its day at ${flight.destination}.`,
    );
  }
  return parts.join(" ");
}

function FlightDetailPanel({ flight, assignments, onClose }) {
  const [showWhy, setShowWhy] = useState(false);
  if (!flight) return null;

  const sameTail = assignments
    .filter((a) => a.tail_number === flight.tail_number)
    .sort((a, b) => a.sequence_order - b.sequence_order);
  const prev =
    sameTail.find((a) => a.sequence_order === flight.sequence_order - 1) ||
    null;
  const next =
    sameTail.find((a) => a.sequence_order === flight.sequence_order + 1) ||
    null;

  const warn = flight.turnaround_warning;

  return (
    <div className="fdp">
      <div className="fdp-head">
        <div className="fdp-title">
          <span className="fdp-flight">{flight.flight_number}</span>
          <span
            className={
              "fdp-badge " + (warn ? "fdp-badge-warn" : "fdp-badge-ok")
            }
          >
            {warn ? "Tight turnaround" : "On schedule"}
          </span>
        </div>
        <button className="fdp-close" onClick={onClose}>
          ✕
        </button>
      </div>

      <div className="fdp-route">
        <div className="fdp-ap">
          <div className="fdp-code">{flight.origin}</div>
          <div className="fdp-time">{fmt(flight.scheduled_departure)}</div>
        </div>
        <div className="fdp-mid">
          <div className="fdp-dur">
            {durationLabel(
              flight.scheduled_departure,
              flight.scheduled_arrival,
            )}
          </div>
          <div className="fdp-arrow">→</div>
        </div>
        <div className="fdp-ap fdp-ap-right">
          <div className="fdp-code">{flight.destination}</div>
          <div className="fdp-time">{fmt(flight.scheduled_arrival)}</div>
        </div>
      </div>

      <div className="fdp-grid">
        <span>Aircraft</span>
        <span>{flight.tail_number} (B737-800)</span>

        <span>Distance</span>
        <span>{flight.distance_km} km</span>

        <span>Estimated fuel</span>
        <span>{Math.round(flight.fuel_kg).toLocaleString()} kg</span>

        <span>Preceding flight</span>
        <span>
          {prev
            ? `${prev.flight_number} ${prev.origin}→${prev.destination} (arr ${fmt(prev.scheduled_arrival)})`
            : "— (first leg)"}
        </span>

        <span>Turnaround</span>
        <span className={warn ? "fdp-warn-text" : ""}>
          {flight.turnaround_minutes != null
            ? `${flight.turnaround_minutes} min${warn ? " ⚠" : ""}`
            : "—"}
        </span>

        <span>Following flight</span>
        <span>
          {next
            ? `${next.flight_number} ${next.origin}→${next.destination} (dep ${fmt(next.scheduled_departure)})`
            : "— (last leg)"}
        </span>
      </div>

      <button className="fdp-why-btn" onClick={() => setShowWhy((s) => !s)}>
        {showWhy ? "Hide explanation" : "Why this rotation?"}
      </button>
      {showWhy && <div className="fdp-why">{buildWhy(flight, prev, next)}</div>}
    </div>
  );
}

export default FlightDetailPanel;
