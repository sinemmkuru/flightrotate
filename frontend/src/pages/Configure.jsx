/*
  Configure page: lets the user set objective weights and GA hyperparameters
  before launching a new optimization run.

  Weight sliders auto-normalize: when one is changed, the other two are
  rescaled so the sum stays 1.0. The user never has to do arithmetic.

  Before running, we check the database has both flights AND aircraft
  (GET /api/status). If either is missing, the Run button is disabled and
  a banner points the user to Data Upload. The backend also guards this,
  so a stale page can't run on an empty dataset.

  Hitting "Run optimization" POSTs to /api/optimize and routes to
  /dashboard on success so the user sees the new run.
*/

import { useState, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";

import { runOptimizationAsync, getOptimizeStatus, getStatus } from "../api/client";
import useAppStore from "../store/useAppStore";
import useAuthStore, { selectIsAdmin } from "../store/useAuthStore";

import "./Configure.css";

// Coverage is a HARD priority — both solvers (GA + CP-SAT) maximize it first and
// never trade it for efficiency, so it is not a tunable weight. The only lever is
// the efficiency-vs-resilience TIE-BREAK between equal-coverage plans: how to
// balance low idle time against turnaround robustness. The two shares sum to 1.0;
// only their ratio affects the result.
const PRESETS = {
  balanced: { idle: 0.5, robustness: 0.5 },
  idle: { idle: 0.8, robustness: 0.2 },
  robustness: { idle: 0.2, robustness: 0.8 },
};

function Configure() {
  const navigate = useNavigate();
  const { isOptimizing, setIsOptimizing } = useAppStore();
  const isAdmin = useAuthStore(selectIsAdmin);

  const [eff, setEff] = useState(PRESETS.balanced);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [params, setParams] = useState({
    population_size: 100,
    generations: 200,
    tournament_size: 3,
    elitism_count: 5,
    mutation_rate: 0.15,
  });
  const [error, setError] = useState(null);
  // Live progress of the background optimization job (null when idle).
  const [progress, setProgress] = useState(null);

  // Data availability gate (B). null = unknown (loading or backend down);
  // we only block when we positively know something is missing.
  const [dataStatus, setDataStatus] = useState(null);

  useEffect(() => {
    getStatus()
      .then(setDataStatus)
      .catch(() => setDataStatus(null));
  }, []);

  const missing = [];
  if (dataStatus) {
    if (dataStatus.flights === 0) missing.push("flights");
    if (dataStatus.aircraft === 0) missing.push("aircraft");
  }
  const noData = missing.length > 0;

  // Idle and robustness shares mirror each other (they sum to 1.0): raising one
  // lowers the other. Coverage is not here — it is always maximized.
  function handleEffChange(key, newValue) {
    const other = key === "idle" ? "robustness" : "idle";
    setEff({ [key]: newValue, [other]: 1 - newValue });
  }

  function applyPreset(name) {
    setEff(PRESETS[name]);
  }

  async function handleRun() {
    setError(null);
    setIsOptimizing(true);
    setProgress(null);
    try {
      // Run in the background and poll for live progress; large GA runs (high
      // generations/population) would otherwise block past the request timeout.
      // Coverage is maximized by the solver as a hard priority (not a weight), so
      // we fix it and split the remainder by the idle/robustness balance — only
      // the idle:robustness ratio drives the efficiency-vs-resilience tie-break.
      const weights = {
        coverage: 0.5,
        idle: 0.5 * eff.idle,
        robustness: 0.5 * eff.robustness,
      };
      const { job_id } = await runOptimizationAsync({
        algorithm: "genetic",
        weights,
        parameters: params,
        seed: Math.floor(Math.random() * 1000000),
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
          navigate("/dashboard"); // completed
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

  return (
    <div className="configure">
      <header>
        <h2>Configure Optimization</h2>
        <p className="subtitle">
          Adjust the objective weights and algorithm parameters, then run.
        </p>
      </header>

      {/* --- Presets --- */}
      <section className="card">
        <h3>Presets</h3>
        <p className="hint">
          Coverage is always maximized first; these only tune how the remaining
          idle vs fuel tie-break is balanced.
        </p>
        <div className="preset-buttons">
          <button
            className="preset-btn"
            onClick={() => applyPreset("balanced")}
          >
            Balanced
            <small>idle 50 / robust 50</small>
          </button>
          <button
            className="preset-btn"
            onClick={() => applyPreset("idle")}
          >
            Most efficient
            <small>idle 80 / robust 20</small>
          </button>
          <button
            className="preset-btn"
            onClick={() => applyPreset("robustness")}
          >
            Most robust
            <small>idle 20 / robust 80</small>
          </button>
        </div>
      </section>

      {/* --- Objective --- */}
      <section className="card">
        <h3>Objective</h3>
        <p className="hint">
          Coverage is a hard priority: both solvers assign as many flights as
          possible first and never drop a flight for efficiency. The sliders below
          only break ties between equal-coverage plans — trading tighter rotations
          (less idle) against more turnaround buffer (delay resilience).
        </p>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "10px 0",
            marginBottom: 10,
            borderBottom: "1px solid var(--border, #2a2a2a)",
          }}
        >
          <div>
            <div className="slider-label">Coverage</div>
            <div className="slider-desc">
              Maximize flights assigned — always on
            </div>
          </div>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#378ADD" }}>
            🔒 Maximized
          </span>
        </div>

        <WeightSlider
          label="Idle time (efficiency)"
          description="Prefer tighter rotations with less aircraft ground time"
          value={eff.idle}
          onChange={(v) => handleEffChange("idle", v)}
          accent="orange"
        />
        <WeightSlider
          label="Robustness (resilience)"
          description="Prefer turnaround buffer above the minimum to absorb delays"
          value={eff.robustness}
          onChange={(v) => handleEffChange("robustness", v)}
          accent="green"
        />
      </section>

      {/* --- Advanced GA parameters --- */}
      <section className="card">
        <button
          className="toggle-btn"
          onClick={() => setShowAdvanced(!showAdvanced)}
        >
          {showAdvanced ? "▾" : "▸"} Advanced parameters
        </button>

        {showAdvanced && (
          <div className="advanced">
            <p className="hint">
              Genetic algorithm hyperparameters. Defaults work well; tune only
              if you understand the trade-offs.
            </p>
            <NumberField
              label="Population size"
              value={params.population_size}
              min={20}
              max={500}
              step={10}
              onChange={(v) => setParams({ ...params, population_size: v })}
            />
            <NumberField
              label="Generations"
              value={params.generations}
              min={50}
              max={1000}
              step={50}
              onChange={(v) => setParams({ ...params, generations: v })}
            />
            <NumberField
              label="Mutation rate"
              value={params.mutation_rate}
              min={0}
              max={1}
              step={0.05}
              onChange={(v) => setParams({ ...params, mutation_rate: v })}
              isFloat
            />
          </div>
        )}
      </section>

      {/* --- Data gate (B) --- */}
      {noData && (
        <div className="error-banner">
          No {missing.join(" or ")} loaded. Head to{" "}
          <Link
            to="/upload"
            style={{ color: "#378ADD", textDecoration: "underline" }}
          >
            Data Upload
          </Link>{" "}
          to generate sample data or upload a CSV before optimizing.
        </div>
      )}

      {/* --- Error & Run --- */}
      {error && <div className="error-banner">{error}</div>}

      <div className="run-section">
        <button
          className="btn btn-primary btn-large"
          onClick={handleRun}
          disabled={isOptimizing || noData || !isAdmin}
        >
          {isOptimizing ? "Running optimization..." : "Run optimization"}
        </button>
        {!isAdmin && (
          <p className="viewer-note">
            Viewer modundasınız — optimizasyon çalıştırmak için admin gerekir.
          </p>
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
        <p className="hint center">
          Runs in the background with live progress; large runs may take a while.
        </p>
      </div>
    </div>
  );
}

/* --- Sub-components --- */

function WeightSlider({ label, description, value, onChange, accent }) {
  const pct = (value * 100).toFixed(0);
  return (
    <div className="slider-row">
      <div className="slider-meta">
        <div>
          <div className="slider-label">{label}</div>
          <div className="slider-desc">{description}</div>
        </div>
        <div className={`slider-value slider-value-${accent}`}>{pct}%</div>
      </div>
      <input
        type="range"
        min={0}
        max={1}
        step={0.01}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className={`slider slider-${accent}`}
      />
    </div>
  );
}

function NumberField({ label, value, min, max, step, onChange, isFloat }) {
  return (
    <div className="number-row">
      <label>{label}</label>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => {
          // Accept both comma and dot as decimal separator (Turkish locales
          // use comma; parseFloat needs dot)
          // 0,15 olarak mutation yapabiliyoruz. 0.15 olmuyordu. python kodunda da virgul kullaniyordu. bu düzeltildi.
          const normalized = e.target.value.replace(",", ".");
          const parsed = isFloat
            ? parseFloat(normalized)
            : parseInt(normalized, 10);
          onChange(Number.isNaN(parsed) ? value : parsed);
        }}
      />
    </div>
  );
}

export default Configure;
