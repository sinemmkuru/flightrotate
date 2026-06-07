import { useEffect, useState } from "react";
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
  Legend,
  Tooltip,
} from "recharts";
import { listRuns, compareRuns } from "../api/client";
import "./Compare.css";

function fmtValue(v, fmt) {
  switch (fmt) {
    case "pct":
      return `${Number(v).toFixed(1)}%`;
    case "min":
      return `${Math.round(v).toLocaleString()} min`;
    case "kg":
      return `${Math.round(v).toLocaleString()} kg`;
    case "usd":
      return `$${Math.round(v).toLocaleString()}`;
    case "sec":
      return `${Number(v).toFixed(1)} s`;
    default:
      return `${Math.round(v).toLocaleString()}`;
  }
}

function fmtDelta(m) {
  const sign = m.delta_percent > 0 ? "+" : "";
  return `${sign}${m.delta_percent.toFixed(1)}%`;
}

function deltaClass(m) {
  if (m.value_a === m.value_b) return "delta-neutral";
  const improved = m.higher_is_better
    ? m.delta_absolute > 0
    : m.delta_absolute < 0;
  return improved ? "delta-good" : "delta-bad";
}

function shortId(id) {
  return id ? id.slice(0, 8) : "";
}

function radarPair(a, b, higherIsBetter) {
  if (a === 0 && b === 0) return [100, 100];
  if (higherIsBetter) {
    const m = Math.max(a, b) || 1;
    return [(a / m) * 100, (b / m) * 100];
  }
  const lo = Math.min(a, b);
  return [a === 0 ? 100 : (lo / a) * 100, b === 0 ? 100 : (lo / b) * 100];
}

function buildRadar(result) {
  const { a, b } = result.scenarios;
  const axes = [
    ["Coverage", a.coverage_pct, b.coverage_pct, true],
    ["Idle", a.idle_minutes, b.idle_minutes, false],
    ["Fuel", a.fuel_kg, b.fuel_kg, false],
    ["Turnaround", a.turnaround_warnings, b.turnaround_warnings, false],
    ["Speed", a.solve_time_seconds, b.solve_time_seconds, false],
  ];
  return axes.map(([metric, av, bv, hib]) => {
    const [sa, sb] = radarPair(av, bv, hib);
    return { metric, A: Math.round(sa), B: Math.round(sb) };
  });
}

function ScenarioCard({ scenario, label, isWinner }) {
  return (
    <div className={`scenario-card ${isWinner ? "scenario-winner" : ""}`}>
      <div className="scenario-head">
        <span className={`scenario-dot dot-${label.toLowerCase()}`} />
        <span className="scenario-name">Scenario {label}</span>
        <span
          className={`badge ${isWinner ? "badge-winner" : "badge-baseline"}`}
        >
          {isWinner ? "Winner" : "Baseline"}
        </span>
      </div>
      <div className="scenario-sub">
        {scenario.algorithm} · run {shortId(scenario.run_id)}
      </div>
      <div className="weight-chips">
        <span className="chip">
          coverage {scenario.weight_coverage.toFixed(2)}
        </span>
        <span className="chip">idle {scenario.weight_idle.toFixed(2)}</span>
        <span className="chip">fuel {scenario.weight_fuel.toFixed(2)}</span>
      </div>
    </div>
  );
}

function Compare() {
  const [runs, setRuns] = useState([]);
  const [runAId, setRunAId] = useState("");
  const [runBId, setRunBId] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadRuns();
  }, []);

  async function loadRuns() {
    try {
      const data = await listRuns();
      const sorted = [...data].sort(
        (x, y) => new Date(y.created_at) - new Date(x.created_at),
      );
      setRuns(sorted);
      if (sorted.length >= 2) {
        setRunAId(sorted[1].run_id);
        setRunBId(sorted[0].run_id);
      }
    } catch (err) {
      setError("Could not load runs from backend.");
    }
  }

  async function handleCompare() {
    if (!runAId || !runBId || runAId === runBId) {
      setError("Pick two different runs to compare.");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await compareRuns(runAId, runBId);
      setResult(data);
    } catch (err) {
      const detail = err.response?.data?.detail || err.message;
      setError(`Compare failed: ${detail}`);
    } finally {
      setLoading(false);
    }
  }

  const radarData = result ? buildRadar(result) : [];

  function runOption(r) {
    const cov =
      r.kpi?.coverage != null ? `${(r.kpi.coverage * 100).toFixed(1)}%` : "";
    return `${shortId(r.run_id)} · ${r.algorithm} · ${cov}`;
  }

  return (
    <div className="compare">
      <div className="page-head">
        <h2>Compare optimizations</h2>
        {result && (
          <span className="page-meta">
            {result.scenarios.a.total_flights} flights · A{" "}
            {result.scenarios.a.assigned_flights} / B{" "}
            {result.scenarios.b.assigned_flights} assigned
          </span>
        )}
      </div>

      <section className="card picker-row">
        <div className="picker">
          <label>Scenario A</label>
          <select value={runAId} onChange={(e) => setRunAId(e.target.value)}>
            <option value="">— select run —</option>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {runOption(r)}
              </option>
            ))}
          </select>
        </div>
        <div className="picker">
          <label>Scenario B</label>
          <select value={runBId} onChange={(e) => setRunBId(e.target.value)}>
            <option value="">— select run —</option>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {runOption(r)}
              </option>
            ))}
          </select>
        </div>
        <button
          onClick={handleCompare}
          disabled={loading || !runAId || !runBId}
          className="btn btn-primary"
        >
          {loading ? "Comparing..." : "Compare"}
        </button>
      </section>

      {error && <div className="error-banner">{error}</div>}
      {runs.length < 2 && !error && (
        <p className="hint">
          You need at least two optimization runs. Head to Configure and run the
          optimizer twice (different presets or seeds), then come back here.
        </p>
      )}

      {result && (
        <>
          <section className="card scenarios-grid">
            <ScenarioCard
              scenario={result.scenarios.a}
              label="A"
              isWinner={result.winner === "A"}
            />
            <ScenarioCard
              scenario={result.scenarios.b}
              label="B"
              isWinner={result.winner === "B"}
            />
          </section>

          <section className="card">
            <h3 className="section-title">Key performance metrics</h3>
            <table className="metrics-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th className="num">Scenario A</th>
                  <th className="num">Scenario B</th>
                  <th className="num">Δ</th>
                  <th className="center">Better</th>
                </tr>
              </thead>
              <tbody>
                {result.metrics.map((m) => (
                  <tr key={m.key}>
                    <td>{m.name}</td>
                    <td className="num">{fmtValue(m.value_a, m.fmt)}</td>
                    <td className="num">{fmtValue(m.value_b, m.fmt)}</td>
                    <td className={`num ${deltaClass(m)}`}>{fmtDelta(m)}</td>
                    <td className="center">
                      {m.better === "tie" ? (
                        <span className="pill pill-tie">—</span>
                      ) : (
                        <span className={`pill pill-${m.better.toLowerCase()}`}>
                          {m.better}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="score-line">
              Scenario A wins {result.a_wins} · Scenario B wins {result.b_wins}
              {result.winner !== "tie" && (
                <>
                  {" "}
                  · <strong>Overall winner: Scenario {result.winner}</strong>
                </>
              )}
            </div>
          </section>

          <section className="card">
            <h3 className="section-title">Multi-dimensional comparison</h3>
            <div className="radar-wrap">
              <ResponsiveContainer width="100%" height={320}>
                <RadarChart data={radarData}>
                  <PolarGrid stroke="var(--border, #2a2a2a)" />
                  <PolarAngleAxis
                    dataKey="metric"
                    tick={{ fill: "var(--text-secondary, #aaa)", fontSize: 12 }}
                  />
                  <PolarRadiusAxis
                    domain={[0, 100]}
                    tick={false}
                    axisLine={false}
                  />
                  <Radar
                    name="Scenario A"
                    dataKey="A"
                    stroke="#888780"
                    fill="#888780"
                    fillOpacity={0.15}
                  />
                  <Radar
                    name="Scenario B"
                    dataKey="B"
                    stroke="#378ADD"
                    fill="#378ADD"
                    fillOpacity={0.25}
                  />
                  <Legend />
                  <Tooltip />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="analysis-box">
            <div className="analysis-head">
              <span className="analysis-bulb">💡</span>
              <span className="analysis-title">Analysis summary</span>
            </div>
            <p className="analysis-text">{result.analysis_text}</p>
          </section>
        </>
      )}
    </div>
  );
}

export default Compare;
