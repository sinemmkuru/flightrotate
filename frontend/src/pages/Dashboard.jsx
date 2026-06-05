/*
  Dashboard: the main view.

  On mount we fetch the list of optimization runs and pick the newest
  one. If there are no runs yet, we show a hint to run one.

  The "Run optimization" button calls POST /api/optimize with default
  weights, then refreshes the view to display the new run.
*/

import { useEffect, useState } from "react";

import { listRuns, runOptimization, getAssignments } from "../api/client";
import useAppStore from "../store/useAppStore";
import KpiCard from "../components/KpiCard";

import "./Dashboard.css";

function Dashboard() {
  const { currentRunId, setCurrentRunId, isOptimizing, setIsOptimizing } =
    useAppStore();

  const [run, setRun] = useState(null);
  const [assignments, setAssignments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // On mount: load runs, pick the newest, fetch its assignments
  useEffect(() => {
    loadLatestRun();
  }, []);

  async function loadLatestRun() {
    setLoading(true);
    setError(null);
    try {
      const runs = await listRuns();
      if (runs.length === 0) {
        setRun(null);
        setAssignments([]);
        setCurrentRunId(null);
      } else {
        const latest = runs[0]; // backend returns newest-first
        setRun(latest);
        setCurrentRunId(latest.run_id);
        const rows = await getAssignments(latest.run_id);
        setAssignments(rows);
      }
    } catch (err) {
      console.error(err);
      setError("Could not load runs. Is the backend running on port 8000?");
    } finally {
      setLoading(false);
    }
  }

  async function handleRunOptimization() {
    setIsOptimizing(true);
    setError(null);
    try {
      await runOptimization({
        algorithm: "genetic",
        weights: { coverage: 0.5, idle: 0.25, fuel: 0.25 },
        seed: 42,
      });
      // Reload to pull in the new run
      await loadLatestRun();
    } catch (err) {
      console.error(err);
      const detail = err.response?.data?.detail || err.message;
      setError(`Optimization failed: ${detail}`);
    } finally {
      setIsOptimizing(false);
    }
  }

  // --- Rendering ---

  if (loading) {
    return <div className="dashboard-empty">Loading...</div>;
  }

  if (error) {
    return (
      <div className="dashboard-empty error">
        {error}
        <button onClick={loadLatestRun} className="btn btn-secondary">
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <div>
          <h2>Dashboard</h2>
          {run && (
            <p className="dashboard-subtitle">
              Run {run.run_id.slice(0, 8)} • {run.algorithm.toUpperCase()} •{" "}
              {new Date(run.created_at).toLocaleString()}
            </p>
          )}
        </div>
        <button
          onClick={handleRunOptimization}
          disabled={isOptimizing}
          className="btn btn-primary"
        >
          {isOptimizing ? "Running..." : "Run optimization"}
        </button>
      </header>

      {!run ? (
        <div className="dashboard-empty">
          No optimization runs yet. Click "Run optimization" to start.
        </div>
      ) : (
        <>
          <section className="kpi-row">
            <KpiCard
              label="Coverage"
              value={`${(run.kpi.coverage * 100).toFixed(1)}`}
              unit="%"
              accent="blue"
            />
            <KpiCard
              label="Assigned flights"
              value={`${run.kpi.assigned_flights}/${run.kpi.total_flights}`}
              accent="green"
            />
            <KpiCard
              label="Idle time"
              value={run.kpi.total_idle_minutes.toLocaleString()}
              unit="min"
              accent="orange"
            />
            <KpiCard
              label="Fuel"
              value={Math.round(run.kpi.total_fuel_kg).toLocaleString()}
              unit="kg"
              accent="orange"
            />
            <KpiCard
              label="Fuel cost"
              value={`$${Math.round(run.kpi.fuel_cost_usd).toLocaleString()}`}
              accent="green"
            />
            <KpiCard
              label="Solve time"
              value={run.kpi.solve_time_seconds.toFixed(1)}
              unit="s"
              accent="blue"
            />
          </section>

          <section className="assignment-section">
            <h3>Assignments ({assignments.length})</h3>
            <div className="table-wrapper">
              <table className="assignment-table">
                <thead>
                  <tr>
                    <th>Aircraft</th>
                    <th>Seq</th>
                    <th>Flight</th>
                    <th>Route</th>
                    <th>Departure</th>
                    <th>Arrival</th>
                    <th>Distance</th>
                    <th>Turnaround</th>
                    <th>Fuel</th>
                  </tr>
                </thead>
                <tbody>
                  {assignments.map((a) => (
                    <tr
                      key={`${a.tail_number}-${a.sequence_order}`}
                      className={a.turnaround_warning ? "row-warning" : ""}
                    >
                      <td>{a.tail_number}</td>
                      <td>{a.sequence_order + 1}</td>
                      <td>{a.flight_number}</td>
                      <td>
                        {a.origin} → {a.destination}
                      </td>
                      <td>{formatTime(a.scheduled_departure)}</td>
                      <td>{formatTime(a.scheduled_arrival)}</td>
                      <td>{a.distance_km} km</td>
                      <td>
                        {a.turnaround_minutes !== null
                          ? `${a.turnaround_minutes} min`
                          : "—"}
                      </td>
                      <td>{Math.round(a.fuel_kg)} kg</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function formatTime(isoString) {
  const d = new Date(isoString);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default Dashboard;
