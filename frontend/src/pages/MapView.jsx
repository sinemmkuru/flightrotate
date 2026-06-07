import { useEffect, useState, useMemo } from "react";
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

function MapView() {
  const [airports, setAirports] = useState([]);
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState("");
  const [assignments, setAssignments] = useState([]);
  const [error, setError] = useState(null);

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
    } catch (e) {
      setError("Could not load map data from backend.");
    }
  }

  async function loadAssignments(id) {
    try {
      const data = await getAssignments(id);
      setAssignments(data);
    } catch (e) {
      setError("Could not load assignments for this run.");
    }
  }

  function onRunChange(e) {
    const id = e.target.value;
    setRunId(id);
    setAssignments([]);
    if (id) loadAssignments(id);
  }

  const airportMap = useMemo(() => {
    const m = {};
    for (const a of airports) m[a.iata_code] = a;
    return m;
  }, [airports]);

  const routes = useMemo(() => {
    const list = [];
    for (const a of assignments) {
      const o = airportMap[a.origin];
      const d = airportMap[a.destination];
      if (!o || !d) continue;
      list.push({
        key: a.flight_id,
        positions: [
          [o.latitude, o.longitude],
          [d.latitude, d.longitude],
        ],
        warning: a.turnaround_warning,
        flight_number: a.flight_number,
        route: `${a.origin} → ${a.destination}`,
        tail: a.tail_number,
      });
    }
    return list;
  }, [assignments, airportMap]);

  return (
    <div className="mapview">
      <div className="page-head">
        <h2>Route map</h2>
        <div className="map-controls">
          <label>Run</label>
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
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            attribution="&copy; OpenStreetMap &copy; CARTO"
            subdomains="abcd"
          />

          {routes.map((r) => (
            <Polyline
              key={r.key}
              positions={r.positions}
              pathOptions={{
                color: r.warning ? "#e0a955" : "#378ADD",
                weight: 1.5,
                opacity: 0.55,
              }}
            >
              <LTooltip sticky>
                {r.flight_number} · {r.route} · {r.tail}
              </LTooltip>
            </Polyline>
          ))}

          {airports.map((a) => (
            <CircleMarker
              key={a.iata_code}
              center={[a.latitude, a.longitude]}
              radius={a.is_operational ? 6 : 3}
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
                {a.is_operational ? " · operational" : ""}
              </LTooltip>
            </CircleMarker>
          ))}
        </MapContainer>
      </div>

      <div className="map-legend">
        <span>
          <span className="dot dot-op" /> Operational airport
        </span>
        <span>
          <span className="dot dot-non" /> Other airport
        </span>
        <span>
          <span className="line line-ok" /> Assigned route
        </span>
        <span>
          <span className="line line-warn" /> Turnaround warning
        </span>
      </div>
    </div>
  );
}

export default MapView;
