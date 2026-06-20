/*
  Map View - route map of an optimization run over Turkey.

  Tier 1 (real schedule/assignment data):
    - Time range filter (presets + adjustable start/end), routes outside the
      window are dimmed.
    - Hourly departure histogram.
    - Route hierarchy: in-window (blue) / outside (dashed grey) / warning (orange).
    - Airport markers sized by traffic; route click -> detail panel; stats; legend.
    - Map / Satellite tile toggle.

  Tier 2 (SIMULATED, schedule-derived - NOT live telemetry):
    - A playback cursor sweeps the selected window. Aircraft airborne at the
      cursor time are drawn as plane icons, their position interpolated along
      the great-circle by flight progress and rotated to the bearing.
    - Derived ground speed (distance / duration) and an assumed cruise level
      are shown, clearly labelled as simulated. ETA = scheduled arrival.
    - Play / pause + speed (1x..60x). At 60x a full day plays in ~24s.
*/

import { useEffect, useMemo, useRef, useState } from "react";
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Polyline,
  Marker,
  Tooltip as LTooltip,
} from "react-leaflet";
import L from "leaflet";
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

const SPEEDS = [1, 5, 10, 30, 60];

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
  const m = ((Math.round(mins) % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}
function bearing(lat1, lon1, lat2, lon2) {
  const toRad = (d) => (d * Math.PI) / 180;
  const toDeg = (r) => (r * 180) / Math.PI;
  const f1 = toRad(lat1),
    f2 = toRad(lat2),
    dl = toRad(lon2 - lon1);
  const y = Math.sin(dl) * Math.cos(f2);
  const x =
    Math.cos(f1) * Math.sin(f2) - Math.sin(f1) * Math.cos(f2) * Math.cos(dl);
  return (toDeg(Math.atan2(y, x)) + 360) % 360;
}
function planeIcon(heading, color) {
  return L.divIcon({
    className: "plane-marker",
    html: `<svg width="22" height="22" viewBox="0 0 22 22" style="transform: rotate(${heading}deg);">
      <path d="M11 2 L5.5 18 L11 14.5 L16.5 18 Z" fill="${color}" stroke="#0b0b0b" stroke-width="1"/>
    </svg>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });
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

  // Tier 2 playback
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(10);
  const winRef = useRef({ start: 0, end: 1440 });
  winRef.current = { start: winStart, end: winEnd };

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
    setCursor((c) => Math.min(Math.max(c, p.start), p.end));
  }
  function setStart(v) {
    const nv = Math.min(v, winEnd);
    setActivePreset(null);
    setWinStart(nv);
    setCursor((c) => Math.max(c, nv));
  }
  function setEnd(v) {
    const nv = Math.max(v, winStart);
    setActivePreset(null);
    setWinEnd(nv);
    setCursor((c) => Math.min(c, nv));
  }

  function togglePlay() {
    setCursor((c) => (c >= winEnd ? winStart : c));
    setPlaying((p) => !p);
  }
  function resetPlay() {
    setPlaying(false);
    setCursor(winStart);
  }

  // Playback loop: advance `speed` simulated-minutes per real second.
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      setCursor((c) => {
        const { start, end } = winRef.current;
        let n = c + speed * 0.1; // tick = 100ms
        if (n > end) n = start;
        return n;
      });
    }, 100);
    return () => clearInterval(id);
  }, [playing, speed]);

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
        const depMin = minsOfDay(a.scheduled_departure);
        let arrMin = minsOfDay(a.scheduled_arrival);
        if (arrMin != null && depMin != null && arrMin < depMin) arrMin += 1440;
        return {
          key: a.flight_id,
          o: [o.latitude, o.longitude],
          d: [d.latitude, d.longitude],
          positions: [
            [o.latitude, o.longitude],
            [d.latitude, d.longitude],
          ],
          depMin,
          arrMin,
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

  const hist = useMemo(() => {
    const b = Array(24).fill(0);
    for (const r of routes)
      if (r.depMin != null) b[Math.floor(r.depMin / 60)] += 1;
    return b;
  }, [routes]);
  const histMax = Math.max(1, ...hist);

  // Aircraft airborne at the cursor time (simulated positions).
  const airborne = useMemo(() => {
    const out = [];
    for (const r of routes) {
      if (r.depMin == null || r.arrMin == null) continue;
      if (cursor < r.depMin || cursor > r.arrMin) continue;
      const span = r.arrMin - r.depMin || 1;
      const p = Math.min(1, Math.max(0, (cursor - r.depMin) / span));
      const lat = r.o[0] + (r.d[0] - r.o[0]) * p;
      const lon = r.o[1] + (r.d[1] - r.o[1]) * p;
      out.push({
        key: r.key,
        lat,
        lon,
        heading: bearing(r.o[0], r.o[1], r.d[0], r.d[1]),
        color: r.warning ? "#e0a955" : "#f0c674",
        progress: Math.round(p * 100),
        flight_number: r.flight_number,
        tail: r.tail,
        route: `${r.origin} → ${r.destination}`,
      });
    }
    return out;
  }, [routes, cursor]);

  const selected = routes.find((r) => r.key === selectedKey) || null;
  const selAir =
    selected &&
    selected.depMin != null &&
    selected.arrMin != null &&
    cursor >= selected.depMin &&
    cursor <= selected.arrMin
      ? {
          progress: Math.round(
            ((cursor - selected.depMin) /
              (selected.arrMin - selected.depMin || 1)) *
              100,
          ),
          speedKts: Math.round(
            selected.distance /
              ((selected.arrMin - selected.depMin) / 60 || 1) /
              1.852,
          ),
        }
      : null;

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

          {/* Simulated airborne aircraft at cursor time */}
          {airborne.map((p) => (
            <Marker
              key={"plane-" + p.key}
              position={[p.lat, p.lon]}
              icon={planeIcon(p.heading, p.color)}
              eventHandlers={{ click: () => setSelectedKey(p.key) }}
            >
              <LTooltip>
                {p.tail} · {p.flight_number} · {p.route} · {p.progress}% (sim)
              </LTooltip>
            </Marker>
          ))}
        </MapContainer>

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
            {selAir && (
              <div className="rd-sim">
                <div className="rd-sim-title">
                  Simulated position @ {fmtMin(cursor)}
                </div>
                <div className="rd-grid">
                  <span>Status</span>
                  <span>In flight</span>
                  <span>Progress</span>
                  <span>{selAir.progress}%</span>
                  <span>ETA</span>
                  <span>{selected.arr}</span>
                  <span>Ground speed</span>
                  <span>~{selAir.speedKts} kts</span>
                  <span>Altitude</span>
                  <span>FL360 (assumed)</span>
                </div>
              </div>
            )}
            {selected.warning && (
              <div className="rd-warn">⚠ Tight turnaround</div>
            )}
          </div>
        )}
      </div>

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
          <span className="lg-plane" /> Airborne now ({airborne.length})
        </span>
      </div>

      <section className="card time-filter">
        <div className="tf-head">
          <h3>Time range filter</h3>
          <span className="tf-showing">
            Showing {fmtMin(winStart)}–{fmtMin(winEnd)} · {inWinRoutes.length}{" "}
            flights
          </span>
        </div>

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
          {/* playback cursor */}
          <line
            x1={(cursor / 1440) * 240}
            y1={2}
            x2={(cursor / 1440) * 240}
            y2={46}
            stroke="#f0c674"
            strokeWidth={1.2}
          />
        </svg>
        <div className="tf-axis">
          <span>00:00</span>
          <span>06:00</span>
          <span>12:00</span>
          <span>18:00</span>
          <span>24:00</span>
        </div>

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

        {/* Playback (simulated) */}
        <div className="tf-playback">
          <button className="tf-play-btn" onClick={togglePlay}>
            {playing ? "⏸ Pause" : "▶ Play"}
          </button>
          <button className="tf-play-btn" onClick={resetPlay}>
            ⏮ Reset
          </button>
          <span className="tf-cursor-time">{fmtMin(cursor)}</span>
          <label className="tf-speed">
            Speed
            <select
              value={speed}
              onChange={(e) => setSpeed(parseInt(e.target.value, 10))}
            >
              {SPEEDS.map((s) => (
                <option key={s} value={s}>
                  {s}×
                </option>
              ))}
            </select>
          </label>
          <span className="tf-sim-note">
            Simulated positions · not live telemetry
          </span>
        </div>
      </section>
    </div>
  );
}

export default MapView;
