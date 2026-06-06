/*
  Configure page: lets the user set objective weights and GA hyperparameters
  before launching a new optimization run.

  Weight sliders auto-normalize: when one is changed, the other two are
  rescaled so the sum stays 1.0. The user never has to do arithmetic.

  Hitting "Run optimization" POSTs to /api/optimize and routes to
  /dashboard on success so the user sees the new run.
*/

import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { runOptimization } from "../api/client";
import useAppStore from "../store/useAppStore";

import "./Configure.css";

const PRESETS = {
  balanced: { coverage: 0.5, idle: 0.25, fuel: 0.25 },
  coverage: { coverage: 0.7, idle: 0.15, fuel: 0.15 },
  efficient: { coverage: 0.3, idle: 0.35, fuel: 0.35 },
};

function Configure() {
  const navigate = useNavigate();
  const { isOptimizing, setIsOptimizing } = useAppStore();

  const [weights, setWeights] = useState(PRESETS.balanced);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [params, setParams] = useState({
    population_size: 100,
    generations: 200,
    tournament_size: 3,
    elitism_count: 5,
    mutation_rate: 0.15,
  });
  const [error, setError] = useState(null);

  function handleWeightChange(key, newValue) {
    // Re-normalize so all three still sum to 1.0.
    // Other two weights keep their relative ratio.
    const otherKeys = ["coverage", "idle", "fuel"].filter((k) => k !== key);
    const remaining = 1 - newValue;
    const otherSum = otherKeys.reduce((acc, k) => acc + weights[k], 0);

    let updated;
    if (otherSum > 0) {
      updated = {
        [key]: newValue,
        [otherKeys[0]]: (weights[otherKeys[0]] / otherSum) * remaining,
        [otherKeys[1]]: (weights[otherKeys[1]] / otherSum) * remaining,
      };
    } else {
      // Edge case: both other weights are 0; split the rest evenly
      updated = {
        [key]: newValue,
        [otherKeys[0]]: remaining / 2,
        [otherKeys[1]]: remaining / 2,
      };
    }
    setWeights(updated);
  }

  function applyPreset(name) {
    setWeights(PRESETS[name]);
  }

  async function handleRun() {
    setError(null);
    setIsOptimizing(true);
    try {
      await runOptimization({
        algorithm: "genetic",
        weights,
        parameters: params,
        seed: 42,
      });
      navigate("/dashboard");
    } catch (err) {
      console.error(err);
      const detail = err.response?.data?.detail || err.message;
      setError(`Optimization failed: ${detail}`);
    } finally {
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
          Quick starting points. You can fine-tune the sliders afterwards.
        </p>
        <div className="preset-buttons">
          <button
            className="preset-btn"
            onClick={() => applyPreset("balanced")}
          >
            Balanced
            <small>50 / 25 / 25</small>
          </button>
          <button
            className="preset-btn"
            onClick={() => applyPreset("coverage")}
          >
            Max coverage
            <small>70 / 15 / 15</small>
          </button>
          <button
            className="preset-btn"
            onClick={() => applyPreset("efficient")}
          >
            Most efficient
            <small>30 / 35 / 35</small>
          </button>
        </div>
      </section>

      {/* --- Objective weights --- */}
      <section className="card">
        <h3>Objective Weights</h3>
        <p className="hint">
          Weights always sum to 1.0; changing one rescales the others.
        </p>

        <WeightSlider
          label="Coverage"
          description="Maximize the number of flights assigned"
          value={weights.coverage}
          onChange={(v) => handleWeightChange("coverage", v)}
          accent="blue"
        />
        <WeightSlider
          label="Idle time"
          description="Minimize aircraft waiting between flights"
          value={weights.idle}
          onChange={(v) => handleWeightChange("idle", v)}
          accent="orange"
        />
        <WeightSlider
          label="Fuel"
          description="Minimize total fuel consumption"
          value={weights.fuel}
          onChange={(v) => handleWeightChange("fuel", v)}
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

      {/* --- Error & Run --- */}
      {error && <div className="error-banner">{error}</div>}

      <div className="run-section">
        <button
          className="btn btn-primary btn-large"
          onClick={handleRun}
          disabled={isOptimizing}
        >
          {isOptimizing ? "Running optimization..." : "Run optimization"}
        </button>
        <p className="hint center">
          Takes ~5-25 seconds depending on parameters and dataset size.
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
