/*
Fleet management page (read-only).

Shows the aircraft fleet in a sortable table: tail number, type, base airport,
when each tail becomes available, its next maintenance date (highlighted when
due soon or overdue), and operational status. Data comes from the read-only
GET /api/fleet/aircraft endpoint.

This is the overview phase; add/edit/delete can be layered on later (the
backend's fleet module is the home for those write operations).
*/
import { useEffect, useMemo, useState } from "react";
import { getFleetAircraft } from "../api/client";
import "./Management.css";

const DAY_MS = 1000 * 60 * 60 * 24;

function Fleet() {
  const [aircraft, setAircraft] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [sort, setSort] = useState({ key: "tail_number", dir: "asc" });

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      setLoading(true);
      const rows = await getFleetAircraft();
      setAircraft(Array.isArray(rows) ? rows : []);
      setError(null);
    } catch (e) {
      setError("Could not load the fleet from backend.");
    } finally {
      setLoading(false);
    }
  }

  function sortVal(a, key) {
    switch (key) {
      case "tail_number":
        return a.tail_number || "";
      case "aircraft_type":
        return a.aircraft_type || "";
      case "base_airport":
        return a.base_airport || "";
      case "available_from":
        return a.available_from
          ? new Date(a.available_from).getTime()
          : -Infinity;
      case "maintenance_due":
        return a.maintenance_due
          ? new Date(a.maintenance_due).getTime()
          : -Infinity;
      case "status":
        return a.status || "";
      default:
        return 0;
    }
  }

  const sorted = useMemo(() => {
    const arr = [...aircraft];
    arr.sort((a, b) => {
      const va = sortVal(a, sort.key);
      const vb = sortVal(b, sort.key);
      const cmp = va < vb ? -1 : va > vb ? 1 : 0;
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [aircraft, sort]);

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

  function statusBadge(status) {
    const s = (status || "").toLowerCase();
    const cls =
      s === "active"
        ? "badge-green"
        : s === "maintenance"
          ? "badge-orange"
          : s === "grounded"
            ? "badge-red"
            : "badge-grey";
    return (
      <span className={`badge ${cls}`}>{(status || "—").toUpperCase()}</span>
    );
  }

  function maintenanceCell(due) {
    if (!due) return <span className="badge-grey badge">none</span>;
    const days = Math.floor((new Date(due) - Date.now()) / DAY_MS);
    const text = new Date(due).toLocaleDateString();
    if (days < 0) return <span className="due-over">{text} (overdue)</span>;
    if (days <= 7)
      return (
        <span className="due-soon">
          {text} ({days}d)
        </span>
      );
    return <span>{text}</span>;
  }

  const activeCount = aircraft.filter(
    (a) => (a.status || "").toLowerCase() === "active",
  ).length;

  const COLUMNS = [
    { key: "tail_number", label: "Tail", sortable: true },
    { key: "aircraft_type", label: "Type", sortable: true },
    { key: "base_airport", label: "Base", sortable: true },
    { key: "available_from", label: "Available from", sortable: true },
    { key: "maintenance_due", label: "Maintenance due", sortable: true },
    { key: "status", label: "Status", sortable: true },
  ];

  return (
    <div className="mgmt">
      <header className="page-head">
        <div>
          <h2>Fleet</h2>
          <p className="mgmt-subtitle">
            {aircraft.length} aircraft · {activeCount} active · click a column
            to sort
          </p>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      {loading ? (
        <div className="mgmt-empty">Loading fleet…</div>
      ) : aircraft.length === 0 ? (
        <div className="mgmt-empty">
          No aircraft found. Upload a fleet CSV from the Data Upload page.
        </div>
      ) : (
        <div className="mgmt-table-wrap">
          <table className="mgmt-table">
            <thead>
              <tr>
                {COLUMNS.map((c) => (
                  <th
                    key={c.key}
                    className={
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
                <tr key={a.tail_number}>
                  <td>
                    <code>{a.tail_number}</code>
                  </td>
                  <td>{a.aircraft_type || "—"}</td>
                  <td>{a.base_airport}</td>
                  <td>
                    {a.available_from
                      ? new Date(a.available_from).toLocaleString()
                      : "—"}
                  </td>
                  <td>{maintenanceCell(a.maintenance_due)}</td>
                  <td>{statusBadge(a.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default Fleet;
