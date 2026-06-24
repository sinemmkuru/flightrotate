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
  getPublishedPlan,
  runOptimizationAsync,
  getOptimizeStatus,
  getAssignments,
  getBaseline,
} from "../api/client";
import useAppStore from "../store/useAppStore";
import useAuthStore, { selectIsAdmin } from "../store/useAuthStore";
import { co2Kg } from "../utils/emissions";
import KpiCard from "../components/KpiCard";
import GanttChart from "../components/GanttChart";
import FlightDetailPanel from "../components/FlightDetailPanel";

import "./Dashboard.css";

// "YYYY-MM-DDTHH:MM" for the current local time, for a datetime-local input.
function nowLocalInput() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

function Dashboard() {
  const { currentRunId, setCurrentRunId, isOptimizing, setIsOptimizing } =
    useAppStore();
  const isAdmin = useAuthStore(selectIsAdmin);

  const [run, setRun] = useState(null);
  const [assignments, setAssignments] = useState([]);
  const [baseline, setBaseline] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedFlight, setSelectedFlight] = useState(null);
  // Planning "as-of" time: flights before it are locked to the prior plan
  // (history); only later flights are optimized. Defaults to now.
  const [asOf, setAsOf] = useState(nowLocalInput);
  // Live progress of a background optimization job (null when idle).
  const [progress, setProgress] = useState(null);
  // Date-range window for the Gantt/table (YYYY-MM-DD). Useful when a published
  // plan spans many days; KPI cards still reflect the whole plan.
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");

  // On mount: load runs, pick the newest, fetch its assignments + baseline
  useEffect(() => {
    loadLatestRun();
  }, []);

  // Reset the date window to a plan's full span when its assignments load.
  function resetDateWindow(rows) {
    if (!rows || rows.length === 0) {
      setFromDate("");
      setToDate("");
      return;
    }
    const dates = rows.map((a) => a.scheduled_departure.slice(0, 10));
    setFromDate(dates.reduce((a, b) => (a < b ? a : b)));
    setToDate(dates.reduce((a, b) => (a > b ? a : b)));
  }

  async function loadLatestRun() {
    setLoading(true);
    setError(null);
    setSelectedFlight(null);
    try {
      // Prefer the published plan of record; fall back to the newest run.
      const published = await getPublishedPlan().catch(() => null);
      let chosen = published;
      if (!chosen) {
        const runs = await listRuns();
        chosen = runs.length > 0 ? runs[0] : null; // newest-first
      }
      if (!chosen) {
        setRun(null);
        setAssignments([]);
        setBaseline(null);
        setCurrentRunId(null);
        resetDateWindow([]);
      } else {
        setRun(chosen);
        setCurrentRunId(chosen.run_id);
        const rows = await getAssignments(chosen.run_id);
        setAssignments(rows);
        resetDateWindow(rows);
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
    setProgress(null);
    try {
      // Start the run in the background and poll for live progress, so large
      // (slow) runs neither block nor hit the request timeout.
      const { job_id } = await runOptimizationAsync({
        algorithm: "genetic",
        weights: { coverage: 0.5, idle: 0.25, fuel: 0.25 },
        seed: 42,
        reference_time: asOf,
      });

      while (true) {
        const status = await getOptimizeStatus(job_id);
        if (status.status === "running") {
          setProgress(status.progress);
          await new Promise((r) => setTimeout(r, 500));
          continue;
        }
        if (status.status === "failed") {
          setError(`Optimization failed: ${status.error}`);
        } else {
          await loadLatestRun(); // completed -> pull in the new run
        }
        break;
      }
    } catch (err) {
      console.error(err);
      const detail = err.response?.data?.detail || err.message;
      setError(`Optimization failed: ${detail}`);
    } finally {
      setProgress(null);
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

  // Date-range windowing for the Gantt/table (KPI cards stay whole-plan).
  const allDates = assignments.map((a) => a.scheduled_departure.slice(0, 10));
  const spanMin = allDates.length ? allDates.reduce((a, b) => (a < b ? a : b)) : "";
  const spanMax = allDates.length ? allDates.reduce((a, b) => (a > b ? a : b)) : "";
  const multiDay = spanMin && spanMax && spanMin !== spanMax;
  const filteredAssignments =
    fromDate && toDate
      ? assignments.filter((a) => {
          const d = a.scheduled_departure.slice(0, 10);
          return d >= fromDate && d <= toDate;
        })
      : assignments;

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <div>
          <h2>Dashboard</h2>
          {run && (
            <p className="dashboard-subtitle">
              {run.status === "published" ? "📌 Published plan" : "Draft (latest run)"}{" "}
              • Run {run.run_id.slice(0, 8)} • {run.algorithm.toUpperCase()} •{" "}
              {new Date(run.created_at).toLocaleString()}
            </p>
          )}
        </div>
        <label className="asof-field" title="Flights before this time are locked to the prior plan; only later flights are optimized.">
          <span>Plan as of</span>
          <input
            type="datetime-local"
            value={asOf}
            onChange={(e) => setAsOf(e.target.value)}
          />
        </label>
        {isAdmin && (
          <button
            onClick={handleRunOptimization}
            disabled={isOptimizing}
            className="btn btn-primary"
          >
            {isOptimizing ? "Running..." : "Run optimization"}
          </button>
        )}
        {run && (
          <span style={{ display: "inline-flex", gap: 8, marginLeft: 8 }}>
            <a
              className="btn"
              href={`http://localhost:8000/api/runs/${run.run_id}/export.csv`}
            >
              Export CSV
            </a>
            <a
              className="btn"
              href={`http://localhost:8000/api/runs/${run.run_id}/export.pdf`}
            >
              Export PDF
            </a>
          </span>
        )}
      </header>

      {run?.stale && (
        <div className="stale-banner">⚠️ {run.stale_detail}</div>
      )}

      {isOptimizing && (
        <div className="optimize-progress">
          {progress && progress.total_generations ? (
            <>
              <div className="op-bar">
                <div
                  className="op-bar-fill"
                  style={{
                    width: `${Math.round(
                      (100 * progress.generation) / progress.total_generations,
                    )}%`,
                  }}
                />
              </div>
              <span className="op-label">
                Generation {progress.generation}/{progress.total_generations}
                {progress.best_fitness != null
                  ? ` · best fitness ${progress.best_fitness}`
                  : ""}
              </span>
            </>
          ) : (
            <span className="op-label">Solving…</span>
          )}
        </div>
      )}

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
              label="CO₂ emissions"
              value={(co2Kg(run.kpi.total_fuel_kg) / 1000).toFixed(1)}
              unit="t"
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
            {multiDay && (
              <div className="date-filter">
                <label>
                  From
                  <input
                    type="date"
                    value={fromDate}
                    min={spanMin}
                    max={spanMax}
                    onChange={(e) => setFromDate(e.target.value)}
                  />
                </label>
                <label>
                  To
                  <input
                    type="date"
                    value={toDate}
                    min={spanMin}
                    max={spanMax}
                    onChange={(e) => setToDate(e.target.value)}
                  />
                </label>
                <button
                  className="btn"
                  onClick={() => {
                    setFromDate(spanMin);
                    setToDate(spanMax);
                  }}
                >
                  Full range
                </button>
                <span className="df-count">
                  {filteredAssignments.length} of {assignments.length} flights
                </span>
              </div>
            )}
            <GanttChart
              assignments={filteredAssignments}
              onSelectFlight={setSelectedFlight}
              referenceTime={run.reference_time}
            />
          </section>

          <section className="assignment-section">
            <h3>
              Assignments ({filteredAssignments.length}
              {filteredAssignments.length !== assignments.length
                ? ` of ${assignments.length}`
                : ""}
              )
            </h3>
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
                  {filteredAssignments.map((a) => (
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
