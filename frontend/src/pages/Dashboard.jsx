/*
  Dashboard: the main view.

  On mount we fetch the list of optimization runs and pick the newest
  one. If there are no runs yet, we show a hint to run one.

  The "Run optimization" button calls POST /api/optimize with default
  weights, then refreshes the view to display the new run.

  Below the KPI cards we show an "Optimizer vs naive baseline" strip: a
  deterministic greedy first-come-first-served assignment is computed on
  the same data (GET /api/baseline) and the optimizer's gains are shown.
  Coverage is compared directly (percentage points); idle and fuel are
  compared PER ASSIGNED FLIGHT so the efficiency gain is fair even when
  the two solutions cover a different number of flights.

  Clicking a flight block in the Gantt opens a slide-in Flight Detail Panel
  with rotation context (preceding/following leg) and a "Why?" explanation.
*/

import { useEffect, useState } from "react";

import {
  listRuns,
  runOptimization,
  getAssignments,
  getBaseline,
} from "../api/client";
import useAppStore from "../store/useAppStore";
import KpiCard from "../components/KpiCard";
import GanttChart from "../components/GanttChart";
import FlightDetailPanel from "../components/FlightDetailPanel";

import "./Dashboard.css";

function Dashboard() {
  const { currentRunId, setCurrentRunId, isOptimizing, setIsOptimizing } =
    useAppStore();

  const [run, setRun] = useState(null);
  const [assignments, setAssignments] = useState([]);
  const [baseline, setBaseline] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedFlight, setSelectedFlight] = useState(null);

  // On mount: load runs, pick the newest, fetch its assignments + baseline
  useEffect(() => {
    loadLatestRun();
  }, []);

  async function loadLatestRun() {
    setLoading(true);
    setError(null);
    setSelectedFlight(null);
    try {
      const runs = await listRuns();
      if (runs.length === 0) {
        setRun(null);
        setAssignments([]);
        setBaseline(null);
        setCurrentRunId(null);
      } else {
        const latest = runs[0]; // backend returns newest-first
        setRun(latest);
        setCurrentRunId(latest.run_id);
        const rows = await getAssignments(latest.run_id);
        setAssignments(rows);
        // Baseline is independent of the run; never let it break the dashboard.
        try {
          const bl = await getBaseline();
          setBaseline(bl);
        } catch (blErr) {
          console.error("baseline fetch failed", blErr);
          setBaseline(null);
        }
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

  // Compute baseline deltas (only when we have both a run and a baseline).
  const bl =
    run && baseline?.available ? buildBaselineDeltas(run, baseline) : null;

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

          {bl && (
            <section className="baseline-strip">
              <div className="baseline-head">
                <span className="baseline-title">
                  Optimizer vs naive baseline
                </span>
                <span className="baseline-sub">
                  Naive = greedy first-come-first-served chaining · covers{" "}
                  {baseline.assigned_flights}/{baseline.total_flights} (
                  {bl.baseCovPP.toFixed(1)}%) · idle &amp; fuel compared per
                  flight
                </span>
              </div>
              <div className="baseline-metrics">
                <BaselineMetric
                  label="Coverage"
                  text={`${bl.covDeltaPP > 0 ? "+" : ""}${bl.covDeltaPP.toFixed(1)} pp`}
                  good={bl.covDeltaPP > 0.05}
                  bad={bl.covDeltaPP < -0.05}
                />
                <BaselineMetric
                  label="Idle / flight"
                  text={`${bl.idleDeltaPct > 0 ? "+" : ""}${bl.idleDeltaPct.toFixed(0)}%`}
                  good={bl.idleDeltaPct < -0.5}
                  bad={bl.idleDeltaPct > 0.5}
                />
                <BaselineMetric
                  label="Fuel / flight"
                  text={`${bl.fuelDeltaPct > 0 ? "+" : ""}${bl.fuelDeltaPct.toFixed(0)}%`}
                  good={bl.fuelDeltaPct < -0.5}
                  bad={bl.fuelDeltaPct > 0.5}
                />
              </div>
            </section>
          )}

          <section className="gantt-section">
            <h3>Aircraft Rotations</h3>
            <p className="hint small">
              Click a flight block for full details and rotation context.
            </p>
            <GanttChart
              assignments={assignments}
              onSelectFlight={setSelectedFlight}
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
                      onClick={() => setSelectedFlight(a)}
                      style={{ cursor: "pointer" }}
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

      <FlightDetailPanel
        flight={selectedFlight}
        assignments={assignments}
        onClose={() => setSelectedFlight(null)}
      />
    </div>
  );
}

// --- Baseline comparison helpers ---

function perFlight(total, assigned) {
  return assigned > 0 ? total / assigned : 0;
}

/*
  Coverage is compared directly as a percentage-point gap. Idle and fuel are
  normalized PER ASSIGNED FLIGHT before comparing, so a solution that covers
  more flights is not unfairly penalized for burning more total fuel. The
  efficiency delta therefore isolates "how well does each assigned flight
  fit into a rotation", independent of how many were covered.
*/
function buildBaselineDeltas(run, baseline) {
  const optCovPP = run.kpi.coverage * 100;
  const baseCovPP = baseline.coverage * 100;
  const covDeltaPP = optCovPP - baseCovPP; // higher is better

  const optIdlePf = perFlight(
    run.kpi.total_idle_minutes,
    run.kpi.assigned_flights,
  );
  const baseIdlePf = perFlight(
    baseline.idle_minutes,
    baseline.assigned_flights,
  );
  const idleDeltaPct =
    baseIdlePf > 0 ? ((optIdlePf - baseIdlePf) / baseIdlePf) * 100 : 0; // lower better

  const optFuelPf = perFlight(run.kpi.total_fuel_kg, run.kpi.assigned_flights);
  const baseFuelPf = perFlight(baseline.fuel_kg, baseline.assigned_flights);
  const fuelDeltaPct =
    baseFuelPf > 0 ? ((optFuelPf - baseFuelPf) / baseFuelPf) * 100 : 0; // lower better

  return { covDeltaPP, idleDeltaPct, fuelDeltaPct, baseCovPP };
}

function BaselineMetric({ label, text, good, bad }) {
  const cls = good ? "delta-good" : bad ? "delta-bad" : "delta-neutral";
  return (
    <div className="bl-metric">
      <span className="bl-label">{label}</span>
      <span className={`bl-delta ${cls}`}>{text}</span>
    </div>
  );
}

function formatTime(isoString) {
  const d = new Date(isoString);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default Dashboard;
