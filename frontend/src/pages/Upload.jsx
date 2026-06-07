/*
  Data Upload page.

  Two paths to populate the database:
    1. Generate synthetic data (the main path for Phase 1) - calls
       POST /api/sample with a chosen size preset. After success the
       user is told how much data was created.
    2. Upload a CSV (placeholder for Phase 2) - file picker is shown
       but not wired up to the backend yet, with a clear note.

  We also show the current database state (flights + aircraft counts)
  so the user knows whether there is anything to optimize.
*/

import { useEffect, useState } from "react";

import { generateSample, listRuns } from "../api/client";
import "./Upload.css";

const SIZE_PRESETS = [
  {
    key: "small",
    label: "Small",
    description: "40 flights · 8 aircraft",
    detail: "Fastest. Good for quick algorithm testing.",
  },
  {
    key: "medium",
    label: "Medium",
    description: "200 flights · 25 aircraft",
    detail: "Default. Mirrors a Turkish carrier's daily domestic load.",
  },
  {
    key: "large",
    label: "Large",
    description: "700 flights · 70 aircraft",
    detail: "Heavy. Tests scalability of the optimizer.",
  },
];

function Upload() {
  const [selectedSize, setSelectedSize] = useState("medium");
  const [generating, setGenerating] = useState(false);
  const [lastGenerated, setLastGenerated] = useState(null);
  const [error, setError] = useState(null);

  // Reuse the backend's run list as a "is there data?" indicator.
  // If there are runs, there must be flights+aircraft (one cannot run
  // an optimization without them).
  const [hasRuns, setHasRuns] = useState(null);

  useEffect(() => {
    checkData();
  }, []);

  async function checkData() {
    try {
      const runs = await listRuns();
      setHasRuns(runs.length > 0);
    } catch {
      setHasRuns(null); // backend down or unreachable
    }
  }

  async function handleGenerate() {
    setGenerating(true);
    setError(null);
    setLastGenerated(null);
    try {
      const result = await generateSample({
        size: selectedSize,
        seed: 42,
        clear_existing: true,
      });
      setLastGenerated(result);
      // Refresh the data indicator
      setHasRuns(false); // new data, no runs yet
    } catch (err) {
      console.error(err);
      const detail = err.response?.data?.detail || err.message;
      setError(`Generation failed: ${detail}`);
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="upload">
      <header>
        <h2>Data Upload</h2>
        <p className="subtitle">
          Load flight schedules and aircraft data into the database.
        </p>
      </header>

      {/* --- Current data status --- */}
      <section className="card status-card">
        <div className="status-row">
          <div className="status-indicator">
            {hasRuns === null && <span className="dot dot-gray" />}
            {hasRuns === true && <span className="dot dot-green" />}
            {hasRuns === false && <span className="dot dot-orange" />}
          </div>
          <div>
            <div className="status-title">
              {hasRuns === null && "Backend unreachable"}
              {hasRuns === true && "Database ready"}
              {hasRuns === false && "No optimization runs yet"}
            </div>
            <div className="status-detail">
              {hasRuns === null &&
                "Could not reach the API on port 8000. Start the backend and refresh."}
              {hasRuns === true &&
                "Flights and aircraft are loaded. Head to Configure to run an optimization."}
              {hasRuns === false &&
                "Generate synthetic data below or upload a CSV to begin."}
            </div>
          </div>
        </div>
      </section>

      {/* --- Sample data generation --- */}
      <section className="card">
        <h3>Generate Synthetic Data</h3>
        <p className="hint">
          Creates a realistic Turkish domestic schedule with hub-weighted
          routing and time-of-day distribution.
        </p>

        <div className="size-picker">
          {SIZE_PRESETS.map((p) => (
            <button
              key={p.key}
              onClick={() => setSelectedSize(p.key)}
              className={
                p.key === selectedSize
                  ? "size-card size-card-active"
                  : "size-card"
              }
            >
              <div className="size-label">{p.label}</div>
              <div className="size-desc">{p.description}</div>
              <div className="size-detail">{p.detail}</div>
            </button>
          ))}
        </div>

        {error && <div className="error-banner">{error}</div>}

        {lastGenerated && (
          <div className="success-banner">
            Generated {lastGenerated.flights_generated} flights and{" "}
            {lastGenerated.aircraft_generated} aircraft for {lastGenerated.date}
            .
          </div>
        )}

        <button
          onClick={handleGenerate}
          disabled={generating}
          className="btn btn-primary btn-large"
        >
          {generating ? "Generating..." : "Generate sample"}
        </button>
        <p className="hint center small">
          Existing flights and aircraft will be cleared first.
        </p>
      </section>

      {/* --- CSV upload (Phase 2 placeholder) --- */}
      <section className="card csv-card">
        <h3>Upload CSV</h3>
        <p className="hint">
          Upload your own flight schedule. Available in a future release.
        </p>
        <div className="csv-dropzone">
          <div className="csv-icon">📄</div>
          <div className="csv-text">Drag & drop a CSV file here</div>
          <div className="csv-subtext">Or browse — coming soon in Phase 2.</div>
        </div>
      </section>
    </div>
  );
}

export default Upload;
