/*
  Map View - route map of an optimization run over Turkey.

  Tier 1 enhancements (all backed by real schedule/assignment data):
    - Time range filter (presets + adjustable start/end) that filters routes
      by scheduled departure. Routes outside the window are dimmed.
    - Hourly departure histogram (in-window hours highlighted).
    - Route hierarchy: in-window (solid blue), outside-window (dashed grey),
      turnaround warning (orange).
    - Airport markers sized by traffic (movement count).
    - Click a route to see its real details (flight, route, times, distance,
      tail, turnaround).
    - Status stats: aircraft active in window / routes in window / total.
    - Map / Satellite tile toggle.

  This visualizes the OPTIMIZED SCHEDULE (a "snapshot"); it is not live
  telemetry. Simulated aircraft positions + playback are a separate,
  clearly-labelled follow-up.
*/

import { useEffect, useMemo, useState } from "react";
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Polyline,
  Tooltip as LTooltip,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { getAirports, listRuns, getAssignments } from "../api/client";
import "./MapView.css";

const TURKEY_CENTER = [39.0, 35.0];

const TILES = {
  map: {
    url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    subdomains: "abcd",
  },
  satellite: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "&copy; Esri",
    subdomains: "",
  },
};

const PRESETS = [
  { key: "morning", label: "Morning", start: 360, end: 540 },
  { key: "midmorning", label: "Mid-morning", start: 540, end: 720 },
  { key: "afternoon", label: "Afternoon", start: 720, end: 1020 },
  { key: "evening", label: "Evening", start: 1020, end: 1320 },
  { key: "fullday", label: "Full day", start: 0, end: 1440 },
];

// "2026-06-19T06:00:00" -> 360 (minutes of day). Parses the HH:MM after 'T'
// directly to avoid any timezone surprises.
function minsOfDay(iso) {
  if (!iso) return null;
  const t = iso.split("T")[1] || "";
  const hh = parseInt(t.slice(0, 2), 10);
  const mm = parseInt(t.slice(3, 5), 10);
  if (Number.isNaN(hh)) return null;
  return hh * 60 + (Number.isNaN(mm) ? 0 : mm);
}

function hhmm(iso) {
  if (!iso) return "";
  return (iso.split("T")[1] || "").slice(0, 5);
}

function fmtMin(mins) {
  const h = Math.floor(mins / 60) % 24;
  const m = mins % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function MapView() {
  const [airports, setAirports] = useState([]);
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState("");
  const [assignments, setAssignments] = useState([]);
  const [error, setError] = useState(null);

  const [winStart, setWinStart] = useState(0);
  const [winEnd, setWinEnd] = useState(1440);
  const [activePreset, setActivePreset] = useState("fullday");
  const [selectedKey, setSelectedKey] = useState(null);
  const [view, setView] = useState("map");

  useEffect(() => {
    init();
  }, []);

  async function init() {
    try {
      const [ap, rs] = await Promise.all([getAirports(), listRuns()]);
      setAirports(ap);
      const sorted = [...rs].sort(
        (x, y) => new Date(y.created_at) - new Date(x.created_at),
      );
      setRuns(sorted);
      if (sorted.length > 0) {
        setRunId(sorted[0].run_id);
        loadAssignments(sorted[0].run_id);
      }
    } catch {
      setError("Could not load map data from backend.");
    }
  }

  async function loadAssignments(id) {
    try {
      setSelectedKey(null);
      const data = await getAssignments(id);
      setAssignments(data);
    } catch {
      setError("Could not load assignments for this run.");
    }
  }

  function onRunChange(e) {
    const id = e.target.value;
    setRunId(id);
    setAssignments([]);
    if (id) loadAssignments(id);
  }

  function applyPreset(p) {
    setActivePreset(p.key);
    setWinStart(p.start);
    setWinEnd(p.end);
  }

  function setStart(v) {
    setActivePreset(null);
    setWinStart(Math.min(v, winEnd));
  }
  function setEnd(v) {
    setActivePreset(null);
    setWinEnd(Math.max(v, winStart));
  }

  const airportMap = useMemo(() => {
    const m = {};
    for (const a of airports) m[a.iata_code] = a;
    return m;
  }, [airports]);

  const routes = useMemo(() => {
    return assignments
      .map((a) => {
        const o = airportMap[a.origin];
        const d = airportMap[a.destination];
        if (!o || !d) return null;
        return {
          key: a.flight_id,
          positions: [
            [o.latitude, o.longitude],
            [d.latitude, d.longitude],
          ],
          depMin: minsOfDay(a.scheduled_departure),
          warning: !!a.turnaround_warning,
          flight_number: a.flight_number,
          origin: a.origin,
          destination: a.destination,
          tail: a.tail_number,
          distance: a.distance_km,
          turnaround: a.turnaround_minutes,
          dep: hhmm(a.scheduled_departure),
          arr: hhmm(a.scheduled_arrival),
        };
      })
      .filter(Boolean);
  }, [assignments, airportMap]);

  const inWindow = (r) =>
    r.depMin != null && r.depMin >= winStart && r.depMin <= winEnd;

  const inWinRoutes = routes.filter(inWindow);
  const outWinRoutes = routes.filter((r) => !inWindow(r));
  const warnCount = inWinRoutes.filter((r) => r.warning).length;
  const aircraftActive = new Set(inWinRoutes.map((r) => r.tail)).size;

  const traffic = useMemo(() => {
    const t = {};
    for (const a of assignments) {
      t[a.origin] = (t[a.origin] || 0) + 1;
      t[a.destination] = (t[a.destination] || 0) + 1;
    }
    return t;
  }, [assignments]);

  // Hourly departure histogram.
  const hist = useMemo(() => {
    const b = Array(24).fill(0);
    for (const r of routes)
      if (r.depMin != null) b[Math.floor(r.depMin / 60)] += 1;
    return b;
  }, [routes]);
  const histMax = Math.max(1, ...hist);

  const selected = routes.find((r) => r.key === selectedKey) || null;
  const tile = TILES[view];

  return (
    <div className="mapview">
      <div className="map-topbar">
        <div className="map-title">
          <h2>Route map</h2>
          <span className="map-stats">
            {aircraftActive} aircraft · {inWinRoutes.length} routes in window ·{" "}
            {routes.length} total
            {warnCount > 0 && (
              <span className="map-warn"> · {warnCount} tight</span>
            )}
          </span>
        </div>
        <div className="map-controls">
          <div className="view-toggle">
            <button
              className={view === "map" ? "vt-on" : ""}
              onClick={() => setView("map")}
            >
              Map
            </button>
            <button
              className={view === "satellite" ? "vt-on" : ""}
              onClick={() => setView("satellite")}
            >
              Satellite
            </button>
          </div>
          <select value={runId} onChange={onRunChange}>
            <option value="">— select run —</option>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.run_id.slice(0, 8)} · {r.algorithm} ·{" "}
                {r.kpi?.coverage != null
                  ? `${(r.kpi.coverage * 100).toFixed(1)}%`
                  : ""}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="map-wrap">
        <MapContainer
          center={TURKEY_CENTER}
          zoom={6}
          className="leaflet-root"
          scrollWheelZoom
        >
          <TileLayer
            key={view}
            url={tile.url}
            attribution={tile.attribution}
            subdomains={tile.subdomains}
          />

          {/* Outside-window routes first (drawn underneath, dimmed). */}
          {outWinRoutes.map((r) => (
            <Polyline
              key={"out-" + r.key}
              positions={r.positions}
              pathOptions={{
                color: "#888780",
                weight: 1,
                opacity: 0.22,
                dashArray: "5,5",
              }}
            />
          ))}

          {/* In-window routes. */}
          {inWinRoutes.map((r) => (
            <Polyline
              key={"in-" + r.key}
              positions={r.positions}
              pathOptions={{
                color: r.warning ? "#e0a955" : "#378ADD",
                weight: selectedKey === r.key ? 4 : 2,
                opacity: 0.85,
              }}
              eventHandlers={{ click: () => setSelectedKey(r.key) }}
            >
              <LTooltip sticky>
                {r.flight_number} · {r.origin} → {r.destination} · {r.tail}
              </LTooltip>
            </Polyline>
          ))}

          {/* Airports, sized by traffic. */}
          {airports.map((a) => {
            const count = traffic[a.iata_code] || 0;
            const radius = count > 0 ? Math.sqrt(count) * 3 + 4 : 3;
            return (
              <CircleMarker
                key={a.iata_code}
                center={[a.latitude, a.longitude]}
                radius={radius}
                pathOptions={{
                  color: a.is_operational ? "#5fb878" : "#888780",
                  fillColor: a.is_operational ? "#5fb878" : "#555555",
                  fillOpacity: 0.9,
                  weight: 1.5,
                }}
              >
                <LTooltip>
                  <strong>{a.iata_code}</strong> — {a.name}
                  {a.city ? `, ${a.city}` : ""}
                  {count > 0 ? ` · ${count} movements` : ""}
                </LTooltip>
              </CircleMarker>
            );
          })}
        </MapContainer>

        {/* Route detail panel (real data). */}
        {selected && (
          <div className="route-detail">
            <div className="rd-head">
              <span className="rd-flight">{selected.flight_number}</span>
              <button className="rd-close" onClick={() => setSelectedKey(null)}>
                ✕
              </button>
            </div>
            <div className="rd-route">
              {selected.origin} → {selected.destination}
            </div>
            <div className="rd-grid">
              <span>Aircraft</span>
              <span>{selected.tail}</span>
              <span>Departure</span>
              <span>{selected.dep}</span>
              <span>Arrival</span>
              <span>{selected.arr}</span>
              <span>Distance</span>
              <span>{selected.distance} km</span>
              <span>Turnaround</span>
              <span>
                {selected.turnaround != null
                  ? `${selected.turnaround} min`
                  : "— (first leg)"}
              </span>
            </div>
            {selected.warning && (
              <div className="rd-warn">⚠ Tight turnaround</div>
            )}
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="map-legend">
        <span>
          <span className="lg-line lg-in" /> In window ({inWinRoutes.length})
        </span>
        <span>
          <span className="lg-line lg-out" /> Outside window (
          {outWinRoutes.length})
        </span>
        <span>
          <span className="lg-line lg-warn" /> Tight turnaround ({warnCount})
        </span>
        <span>
          <span className="lg-dot lg-op" /> Operational airport
        </span>
        <span>
          <span className="lg-dot lg-non" /> Other airport
        </span>
      </div>

      {/* Time range filter */}
      <section className="card time-filter">
        <div className="tf-head">
          <h3>Time range filter</h3>
          <span className="tf-showing">
            Showing {fmtMin(winStart)}–{fmtMin(winEnd)} · {inWinRoutes.length}{" "}
            flights
          </span>
        </div>

        {/* Hourly histogram */}
        <svg
          className="tf-hist"
          viewBox="0 0 240 48"
          preserveAspectRatio="none"
        >
          {hist.map((c, h) => {
            const within = h * 60 >= winStart && h * 60 < winEnd;
            const barH = (c / histMax) * 40;
            return (
              <rect
                key={h}
                x={h * 10 + 1}
                y={44 - barH}
                width={8}
                height={barH}
                rx={1}
                fill={within ? "#378ADD" : "#3a3a3a"}
              />
            );
          })}
        </svg>
        <div className="tf-axis">
          <span>00:00</span>
          <span>06:00</span>
          <span>12:00</span>
          <span>18:00</span>
          <span>24:00</span>
        </div>

        {/* Adjustable start / end */}
        <div className="tf-sliders">
          <label>
            Start <strong>{fmtMin(winStart)}</strong>
          </label>
          <input
            type="range"
            min={0}
            max={1440}
            step={15}
            value={winStart}
            onChange={(e) => setStart(parseInt(e.target.value, 10))}
          />
          <label>
            End <strong>{fmtMin(winEnd)}</strong>
          </label>
          <input
            type="range"
            min={0}
            max={1440}
            step={15}
            value={winEnd}
            onChange={(e) => setEnd(parseInt(e.target.value, 10))}
          />
        </div>

        {/* Presets */}
        <div className="tf-presets">
          {PRESETS.map((p) => (
            <button
              key={p.key}
              className={
                activePreset === p.key ? "tf-preset tf-preset-on" : "tf-preset"
              }
              onClick={() => applyPreset(p)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

export default MapView;
