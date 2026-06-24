/*
  Disruption page: a "what-if" recovery tool.

  Pick a disruption -- ground an aircraft (AOG) or cancel a flight -- and the
  backend re-optimizes the current schedule with CP-SAT and reports the impact:
  before/after KPIs, how many flights were re-sequenced / dropped / added, and
  a plain-language summary.

  Tail and flight options come from the latest run's assignments, so the user
  picks from real aircraft/flights that are actually in the schedule.
*/

import { useEffect, useState } from "react";

import { listRuns, getAssignments, disrupt } from "../api/client";
import useAuthStore, { selectIsAdmin } from "../store/useAuthStore";
import "./Disruption.css";

function fmtTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function Disruption() {
  const isAdmin = useAuthStore(selectIsAdmin);
  const [assignments, setAssignments] = useState([]);
  const [hasRun, setHasRun] = useState(false);
  const [loadingData, setLoadingData] = useState(true);
  const [dataError, setDataError] = useState(null);

  const [dtype, setDtype] = useState("ground_aircraft");
  const [tail, setTail] = useState("");
  const [flightId, setFlightId] = useState("");
  const [delayMinutes, setDelayMinutes] = useState(60);

  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoadingData(true);
    setDataError(null);
    try {
      const runs = await listRuns();
      if (runs.length === 0) {
        setHasRun(false);
        setAssignments([]);
      } else {
        setHasRun(true);
        const rows = await getAssignments(runs[0].run_id);
        setAssignments(rows);
        const tails = uniqueTails(rows);
        if (tails.length) setTail(tails[0]);
        if (rows.length) setFlightId(rows[0].flight_id);
      }
    } catch (e) {
      console.error(e);
      setDataError(
        "Could not load the current schedule. Is the backend running on port 8000?",
      );
    } finally {
      setLoadingData(false);
    }
  }

  function uniqueTails(rows) {
    const counts = {};
    rows.forEach((r) => {
      counts[r.tail_number] = (counts[r.tail_number] || 0) + 1;
    });
    return Object.keys(counts).sort();
  }

  function legCount(t) {
    return assignments.filter((r) => r.tail_number === t).length;
  }

  async function handleSimulate() {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      let body;
      if (dtype === "ground_aircraft") {
        body = { type: "ground_aircraft", tail_number: tail };
      } else if (dtype === "cancel") {
        body = { type: "cancel", flight_id: flightId };
      } else {
        body = {
          type: "delay",
          flight_id: flightId,
          delay_minutes: Number(delayMinutes),
        };
      }
      const data = await disrupt(body);
      setResult(data);
    } catch (e) {
      const detail = e.response?.data?.detail || e.message;
      setError(
        `Simulation failed: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`,
      );
    } finally {
      setRunning(false);
    }
  }

  const tails = uniqueTails(assignments);

  return (
    <div className="disruption">
      <div className="page-head">
        <h2>Disruption &amp; recovery</h2>
        <span className="page-meta">
          Simulate an operational disruption and see how the optimizer recovers.
        </span>
      </div>

      {loadingData ? (
        <div className="card hint">Loading current schedule...</div>
      ) : dataError ? (
        <div className="error-banner">{dataError}</div>
      ) : !hasRun ? (
        <div className="card hint">
          No optimization runs yet. Run the optimizer once (Dashboard or
          Configure), then come back to simulate a disruption on the schedule.
        </div>
      ) : (
        <>
          {/* --- Controls --- */}
          <section className="card controls">
            <div className="seg">
              <button
                className={`seg-btn ${dtype === "ground_aircraft" ? "seg-active" : ""}`}
                onClick={() => setDtype("ground_aircraft")}
              >
                Ground aircraft (AOG)
              </button>
              <button
                className={`seg-btn ${dtype === "cancel" ? "seg-active" : ""}`}
                onClick={() => setDtype("cancel")}
              >
                Cancel flight
              </button>
              <button
                className={`seg-btn ${dtype === "delay" ? "seg-active" : ""}`}
                onClick={() => setDtype("delay")}
              >
                Delay flight
              </button>
            </div>

            {dtype === "ground_aircraft" && (
              <div className="picker">
                <label>Aircraft to ground</label>
                <select value={tail} onChange={(e) => setTail(e.target.value)}>
                  {tails.map((t) => (
                    <option key={t} value={t}>
                      {t} ({legCount(t)} legs)
                    </option>
                  ))}
                </select>
              </div>
            )}

            {(dtype === "cancel" || dtype === "delay") && (
              <div className="picker">
                <label>{dtype === "delay" ? "Flight to delay" : "Flight to cancel"}</label>
                <select
                  value={flightId}
                  onChange={(e) => setFlightId(e.target.value)}
                >
                  {assignments.map((r) => (
                    <option key={r.flight_id} value={r.flight_id}>
                      {r.flight_number} · {r.origin}→{r.destination} ·{" "}
                      {fmtTime(r.scheduled_departure)}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {dtype === "delay" && (
              <div className="picker">
                <label>Delay (minutes)</label>
                <input
                  type="number"
                  min="1"
                  step="5"
                  value={delayMinutes}
                  onChange={(e) => setDelayMinutes(e.target.value)}
                />
              </div>
            )}

            <button
              className="btn btn-primary"
              onClick={handleSimulate}
              disabled={
                running ||
                !isAdmin ||
                (dtype === "ground_aircraft"
                  ? !tail
                  : !flightId) ||
                (dtype === "delay" && !(Number(delayMinutes) > 0))
              }
            >
              {running ? "Simulating..." : "Simulate disruption"}
            </button>
            {!isAdmin && (
              <p className="viewer-note">
                Viewer modundasınız — kesinti simülasyonu için admin gerekir.
              </p>
            )}
          </section>

          {error && <div className="error-banner">{error}</div>}

          {/* --- Result --- */}
          {result && (
            <>
              <section className="summary-box">
                <span className="summary-icon">⚠️</span>
                <p className="summary-text">{result.summary}</p>
              </section>

              {result.delay_propagation && (
                <section className="card">
                  <h3 className="section-title">
                    Reactionary delay (if the plan is flown as-is)
                  </h3>
                  <div className="impact-chips">
                    <Chip
                      n={result.delay_propagation.flights_delayed}
                      label="flights delayed"
                      cls="ic-moved"
                    />
                    <Chip
                      n={result.delay_propagation.total_reactionary_delay_min}
                      label="min knock-on delay"
                      cls="ic-dropped"
                    />
                    <Chip
                      n={result.delay_propagation.max_delay_min}
                      label="min worst single delay"
                      cls="ic-cancelled"
                    />
                  </div>
                  <table className="affected-table">
                    <thead>
                      <tr>
                        <th>Flight</th>
                        <th>Route</th>
                        <th>Scheduled</th>
                        <th>Actual</th>
                        <th>Delay</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.delay_propagation.affected.map((r) => (
                        <tr key={r.flight_id}>
                          <td>{r.flight_number}</td>
                          <td>{r.route.replace("->", " → ")}</td>
                          <td>{fmtTime(r.scheduled_departure)}</td>
                          <td>{fmtTime(r.actual_departure)}</td>
                          <td>+{r.delay_minutes} min</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="ba-note">
                    Each aircraft keeps its planned rotation; the delay ripples
                    down its later legs, absorbed by turnaround slack. The
                    Before/After table below contrasts flying this plan as-is
                    with re-optimizing (tail swaps) around the new departure
                    time.
                  </p>
                </section>
              )}

              <section className="card">
                <h3 className="section-title">Before vs after</h3>
                <table className="ba-table">
                  <thead>
                    <tr>
                      <th>Metric</th>
                      <th className="num">Before</th>
                      <th className="num">After</th>
                      <th className="num">Δ</th>
                    </tr>
                  </thead>
                  <tbody>
                    <BaRow
                      label="Coverage"
                      before={`${(result.before.coverage * 100).toFixed(1)}%`}
                      after={`${(result.after.coverage * 100).toFixed(1)}%`}
                      delta={`${signPp(result.after.coverage - result.before.coverage)}`}
                      deltaClass={coverageClass(
                        result.after.coverage - result.before.coverage,
                      )}
                    />
                    <BaRow
                      label="Assigned flights"
                      before={`${result.before.assigned_flights}/${result.before.total_flights}`}
                      after={`${result.after.assigned_flights}/${result.after.total_flights}`}
                      delta=""
                    />
                    <BaRow
                      label="Idle time"
                      before={`${Math.round(result.before.idle_minutes).toLocaleString()} min`}
                      after={`${Math.round(result.after.idle_minutes).toLocaleString()} min`}
                      delta={signNum(
                        result.after.idle_minutes - result.before.idle_minutes,
                        "min",
                      )}
                    />
                    <BaRow
                      label="Fuel"
                      before={`${Math.round(result.before.fuel_kg).toLocaleString()} kg`}
                      after={`${Math.round(result.after.fuel_kg).toLocaleString()} kg`}
                      delta={signNum(
                        result.after.fuel_kg - result.before.fuel_kg,
                        "kg",
                      )}
                    />
                    <BaRow
                      label="Fuel cost"
                      before={`$${Math.round(result.before.fuel_cost_usd).toLocaleString()}`}
                      after={`$${Math.round(result.after.fuel_cost_usd).toLocaleString()}`}
                      delta={signNum(
                        result.after.fuel_cost_usd -
                          result.before.fuel_cost_usd,
                        "usd",
                      )}
                    />
                  </tbody>
                </table>
                <p className="ba-note">
                  Recovery is re-optimized with CP-SAT. Idle/fuel changes
                  reflect the new (tighter or smaller) schedule, not a quality
                  regression.
                </p>
              </section>

              <section className="card">
                <h3 className="section-title">Impact</h3>
                <div className="impact-chips">
                  <Chip
                    n={result.impact.flights_cancelled}
                    label="cancelled"
                    cls="ic-cancelled"
                  />
                  <Chip
                    n={result.impact.flights_dropped}
                    label="dropped"
                    cls="ic-dropped"
                  />
                  <Chip
                    n={result.impact.flights_moved}
                    label="re-sequenced"
                    cls="ic-moved"
                  />
                  <Chip
                    n={result.impact.flights_added}
                    label="picked up"
                    cls="ic-added"
                  />
                  <Chip
                    n={result.impact.flights_unchanged}
                    label="unchanged"
                    cls="ic-unchanged"
                  />
                </div>

                {result.impact.affected.length > 0 && (
                  <table className="affected-table">
                    <thead>
                      <tr>
                        <th>Change</th>
                        <th>Flight</th>
                        <th>Route</th>
                        <th>Detail</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.impact.affected.map((a) => (
                        <tr key={a.flight_id}>
                          <td>
                            <span className={`badge badge-${a.change}`}>
                              {a.change}
                            </span>
                          </td>
                          <td>{a.flight_number}</td>
                          <td>{a.route.replace("->", " → ")}</td>
                          <td className="detail">{a.detail}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}

function BaRow({ label, before, after, delta, deltaClass }) {
  return (
    <tr>
      <td>{label}</td>
      <td className="num">{before}</td>
      <td className="num">{after}</td>
      <td className={`num ${deltaClass || "delta-neutral"}`}>{delta}</td>
    </tr>
  );
}

function Chip({ n, label, cls }) {
  return (
    <span className={`impact-chip ${cls}`}>
      <strong>{n}</strong> {label}
    </span>
  );
}

function signPp(deltaFraction) {
  const pp = deltaFraction * 100;
  if (Math.abs(pp) < 0.05) return "0.0 pp";
  return `${pp > 0 ? "+" : ""}${pp.toFixed(1)} pp`;
}

function coverageClass(deltaFraction) {
  const pp = deltaFraction * 100;
  if (Math.abs(pp) < 0.05) return "delta-neutral";
  return pp > 0 ? "delta-good" : "delta-bad";
}

function signNum(delta, unit) {
  if (Math.abs(delta) < 0.5) return "—";
  const sign = delta > 0 ? "+" : "−";
  const v = Math.abs(Math.round(delta)).toLocaleString();
  if (unit === "usd") return `${sign}$${v}`;
  return `${sign}${v} ${unit}`;
}

export default Disruption;
