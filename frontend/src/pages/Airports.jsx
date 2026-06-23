/*
Airport management page (read-only).

Shows the airport master data in a sortable table: IATA/ICAO codes, name,
city, coordinates, the per-airport minimum turnaround, and whether the airport
is operational (the synthetic generator creates flights for operational
airports; others are display-only on the map). Data comes from the read-only
GET /api/fleet/airports endpoint.

Overview phase; edit (e.g. min turnaround, operational flag) can be layered on
later via the backend fleet module.
*/
import { useEffect, useMemo, useState } from "react";
import { getFleetAirports } from "../api/client";
import "./Management.css";

function Airports() {
  const [airports, setAirports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [sort, setSort] = useState({ key: "iata_code", dir: "asc" });

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      setLoading(true);
      const rows = await getFleetAirports();
      setAirports(Array.isArray(rows) ? rows : []);
      setError(null);
    } catch (e) {
      setError("Could not load airports from backend.");
    } finally {
      setLoading(false);
    }
  }

  function sortVal(a, key) {
    switch (key) {
      case "iata_code":
        return a.iata_code || "";
      case "icao_code":
        return a.icao_code || "";
      case "name":
        return a.name || "";
      case "city":
        return a.city || "";
      case "latitude":
        return a.latitude ?? 0;
      case "longitude":
        return a.longitude ?? 0;
      case "min_turnaround_min":
        return a.min_turnaround_min ?? 0;
      case "is_operational":
        return a.is_operational ? 1 : 0;
      default:
        return 0;
    }
  }

  const sorted = useMemo(() => {
    const arr = [...airports];
    arr.sort((a, b) => {
      const va = sortVal(a, sort.key);
      const vb = sortVal(b, sort.key);
      const cmp = va < vb ? -1 : va > vb ? 1 : 0;
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [airports, sort]);

  function toggleSort(key) {
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" },
    );
  }
  function arrow(key) {
    if (sort.key !== key) return "";
    return sort.dir === "asc" ? " ▲" : " ▼";
  }

  const opCount = airports.filter((a) => a.is_operational).length;

  const COLUMNS = [
    { key: "iata_code", label: "Code", sortable: true },
    { key: "icao_code", label: "ICAO", sortable: true },
    { key: "name", label: "Name", sortable: true },
    { key: "city", label: "City", sortable: true },
    { key: "latitude", label: "Lat", sortable: true, num: true },
    { key: "longitude", label: "Lon", sortable: true, num: true },
    {
      key: "min_turnaround_min",
      label: "Min turn (min)",
      sortable: true,
      num: true,
    },
    { key: "is_operational", label: "Operational", sortable: true },
  ];

  return (
    <div className="mgmt">
      <header className="page-head">
        <div>
          <h2>Airports</h2>
          <p className="mgmt-subtitle">
            {airports.length} airports · {opCount} operational · click a column
            to sort
          </p>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      {loading ? (
        <div className="mgmt-empty">Loading airports…</div>
      ) : airports.length === 0 ? (
        <div className="mgmt-empty">No airports found.</div>
      ) : (
        <div className="mgmt-table-wrap">
          <table className="mgmt-table">
            <thead>
              <tr>
                {COLUMNS.map((c) => (
                  <th
                    key={c.key}
                    className={
                      (c.num ? "num " : "") +
                      (c.sortable ? "sortable " : "") +
                      (sort.key === c.key ? "sorted" : "")
                    }
                    onClick={c.sortable ? () => toggleSort(c.key) : undefined}
                  >
                    {c.label}
                    {c.sortable ? arrow(c.key) : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((a) => (
                <tr key={a.iata_code}>
                  <td>
                    <code>{a.iata_code}</code>
                  </td>
                  <td>
                    <code>{a.icao_code || "—"}</code>
                  </td>
                  <td>{a.name}</td>
                  <td>{a.city || "—"}</td>
                  <td className="num">{(a.latitude ?? 0).toFixed(4)}</td>
                  <td className="num">{(a.longitude ?? 0).toFixed(4)}</td>
                  <td className="num">{a.min_turnaround_min ?? "—"}</td>
                  <td>
                    {a.is_operational ? (
                      <span className="badge badge-green">operational</span>
                    ) : (
                      <span className="badge badge-grey">display-only</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default Airports;
