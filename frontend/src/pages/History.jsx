/*
Optimization History page.

Lists every past optimization run with its KPIs in a sortable table, so the
user can browse the run log (like a commercial ops "run history"), spot the
best run at a glance, and export any run's results. The newest run is badged.
Sorting is client-side on any column header.

The backend already exposes GET /api/runs (newest-first); this page is a
read-only view over it and reuses the export endpoints for per-row download.
To compare two runs side by side, use the Compare page.
*/
import { useEffect, useMemo, useState } from "react";
import { listRuns, publishRun, unpublishRun } from "../api/client";
import useAuthStore, { selectIsAdmin } from "../store/useAuthStore";
import "./History.css";

// Dev/demo API base; change if the backend is deployed elsewhere.
const API_BASE = "http://localhost:8000/api";

function History() {
  const isAdmin = useAuthStore(selectIsAdmin);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [sort, setSort] = useState({ key: "created_at", dir: "desc" });

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      setLoading(true);
      const rs = await listRuns();
      setRuns(Array.isArray(rs) ? rs : []);
      setError(null);
    } catch (e) {
      setError("Could not load runs from backend.");
    } finally {
      setLoading(false);
    }
  }

  // run_id of the newest run, for the "latest" badge.
  const newestId = useMemo(() => {
    if (runs.length === 0) return null;
    return [...runs].sort(
      (a, b) => new Date(b.created_at) - new Date(a.created_at),
    )[0].run_id;
  }, [runs]);

  // Sort value extractor (handles the nested kpi object).
  function sortVal(run, key) {
    const k = run.kpi || {};
    switch (key) {
      case "created_at":
        return new Date(run.created_at).getTime();
      case "algorithm":
        return run.algorithm || "";
      case "coverage":
        return k.coverage ?? 0;
      case "assigned":
        return k.assigned_flights ?? 0;
      case "idle":
        return k.total_idle_minutes ?? 0;
      case "fuel":
        return k.total_fuel_kg ?? 0;
      case "cost":
        return k.fuel_cost_usd ?? 0;
      case "solve":
        return k.solve_time_seconds ?? 0;
      default:
        return 0;
    }
  }

  const sortedRuns = useMemo(() => {
    const arr = [...runs];
    arr.sort((a, b) => {
      const va = sortVal(a, sort.key);
      const vb = sortVal(b, sort.key);
      const cmp = va < vb ? -1 : va > vb ? 1 : 0;
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [runs, sort]);

  async function setPlan(runId, publish) {
    try {
      if (publish) await publishRun(runId);
      else await unpublishRun(runId);
      await load(); // refresh statuses (single-publish may have demoted another)
    } catch {
      setError("Could not update the plan status.");
    }
  }

  function toggleSort(key) {
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "desc" },
    );
  }

  function arrow(key) {
    if (sort.key !== key) return "";
    return sort.dir === "asc" ? " ▲" : " ▼";
  }

  const COLUMNS = [
    { key: "created_at", label: "Created", sortable: true },
    { key: "algorithm", label: "Algorithm", sortable: true },
    { key: "coverage", label: "Coverage", sortable: true, num: true },
    { key: "assigned", label: "Assigned", sortable: true, num: true },
    { key: "idle", label: "Idle (min)", sortable: true, num: true },
    { key: "fuel", label: "Fuel (kg)", sortable: true, num: true },
    { key: "cost", label: "Cost ($)", sortable: true, num: true },
    { key: "solve", label: "Solve (s)", sortable: true, num: true },
    { key: "run", label: "Run", sortable: false },
    { key: "plan", label: "Plan", sortable: false },
    { key: "export", label: "Export", sortable: false },
  ];

  return (
    <div className="history">
      <header className="page-head">
        <div>
          <h2>Optimization History</h2>
          <p className="history-subtitle">
            {runs.length} run{runs.length === 1 ? "" : "s"} · click a column to
            sort
          </p>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      {loading ? (
        <div className="history-empty">Loading runs…</div>
      ) : runs.length === 0 ? (
        <div className="history-empty">
          No optimization runs yet. Run one from the Dashboard.
        </div>
      ) : (
        <div className="history-table-wrap">
          <table className="history-table">
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
              {sortedRuns.map((run) => {
                const k = run.kpi || {};
                const isNewest = run.run_id === newestId;
                const isPublished = run.status === "published";
                return (
                  <tr
                    key={run.run_id}
                    className={
                      isPublished ? "row-published" : isNewest ? "row-newest" : ""
                    }
                  >
                    <td>{new Date(run.created_at).toLocaleString()}</td>
                    <td>
                      <span className="algo-pill">
                        {(run.algorithm || "—").toUpperCase()}
                      </span>
                    </td>
                    <td className="num">
                      {((k.coverage ?? 0) * 100).toFixed(1)}%
                    </td>
                    <td className="num">
                      {k.assigned_flights ?? 0}/{k.total_flights ?? 0}
                    </td>
                    <td className="num">
                      {(k.total_idle_minutes ?? 0).toLocaleString()}
                    </td>
                    <td className="num">
                      {Math.round(k.total_fuel_kg ?? 0).toLocaleString()}
                    </td>
                    <td className="num">
                      ${Math.round(k.fuel_cost_usd ?? 0).toLocaleString()}
                    </td>
                    <td className="num">
                      {(k.solve_time_seconds ?? 0).toFixed(1)}
                    </td>
                    <td className="run-cell">
                      <code>{run.run_id.slice(0, 8)}</code>
                      {isNewest && <span className="latest-badge">latest</span>}
                    </td>
                    <td className="plan-cell">
                      {isPublished && (
                        <span className="published-badge">PUBLISHED</span>
                      )}
                      {isAdmin ? (
                        <button
                          className="plan-btn"
                          onClick={() => setPlan(run.run_id, !isPublished)}
                        >
                          {isPublished ? "Unpublish" : "Publish"}
                        </button>
                      ) : (
                        !isPublished && <span className="run-cell">—</span>
                      )}
                    </td>
                    <td className="export-cell">
                      <a
                        className="export-link"
                        href={`${API_BASE}/runs/${run.run_id}/export.csv`}
                      >
                        CSV
                      </a>
                      <a
                        className="export-link"
                        href={`${API_BASE}/runs/${run.run_id}/export.pdf`}
                      >
                        PDF
                      </a>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {runs.length > 0 && (
        <p className="history-hint">
          To compare two runs side by side, open the Compare page.
        </p>
      )}
    </div>
  );
}

export default History;
