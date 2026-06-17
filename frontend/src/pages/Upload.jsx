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
import { generateSample, listRuns, uploadFlights } from "../api/client";
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

function formatUploadError(err) {
  switch (err.type) {
    case "missing_columns":
      return `Missing required column(s): ${err.columns.join(", ")}`;
    case "invalid_time_format":
      return `Row ${err.row}: "${err.value}" in ${err.column} is not a valid HH:MM time.`;
    case "unknown_airport":
      return `Row ${err.row}: unknown airport "${err.value}" in ${err.column}.`;
    case "same_origin_destination":
      return `Row ${err.row}: origin and destination are the same ("${err.value}").`;
    case "missing_value":
      return `Row ${err.row}: missing ${err.column}.`;
    case "empty_file":
      return "The file has no data rows.";
    case "not_csv":
      return "Please select a .csv file.";
    case "server_error":
      return err.message || "Server error during upload.";
    default:
      return JSON.stringify(err);
  }
}

function formatUploadWarning(w) {
  switch (w.type) {
    case "duplicate_flight_id":
      return `Duplicate flight_id "${w.value}" on row(s) ${w.rows.join(", ")}.`;
    case "no_aircraft":
      return w.message;
    default:
      return JSON.stringify(w);
  }
}

function Upload() {
  const [selectedSize, setSelectedSize] = useState("medium");
  const [generating, setGenerating] = useState(false);
  const [lastGenerated, setLastGenerated] = useState(null);
  const [error, setError] = useState(null);

  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const [dragOver, setDragOver] = useState(false);

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

  async function handleFile(file) {
    if (!file) return;
    setUploadResult(null);
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setUploadResult({ ok: false, flights_imported: 0, errors: [{ type: "not_csv" }], warnings: [] });
      return;
    }
    setUploading(true);
    try {
      const res = await uploadFlights(file);
      setUploadResult(res);
    } catch (e) {
      let detail = "Upload failed.";
      const d = e?.response?.data?.detail;
      if (typeof d === "string") {
        detail = d;
      } else if (Array.isArray(d) && d.length && d[0]?.msg) {
        detail = d.map((x) => x.msg).join("; ");
      }
      setUploadResult({
        ok: false,
        flights_imported: 0,
        errors: [{ type: "server_error", message: detail }],
        warnings: [],
      });
    } finally {
      setUploading(false);
    }
  }

  function onDrop(e) {
    e.preventDefault();
    setDragOver(false);
    handleFile(e.dataTransfer.files?.[0]);
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
      {/* --- CSV upload --- */}
      <section className="card csv-card">
        <h3>Upload CSV</h3>
        <p className="hint">
          Upload your own flight schedule. The existing fleet and airports are
          kept; only the flight schedule is replaced.
        </p>

        <div className="csv-required">
          <span className="csv-required-label">Required columns:</span>
          {["flight_id", "origin", "destination", "dep_time", "arr_time"].map((c) => (
            <span key={c} className="csv-chip">{c}</span>
          ))}
        </div>

        <label
          className={"csv-dropzone" + (dragOver ? " csv-dropzone-active" : "")}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
        >
          <input
            type="file"
            accept=".csv"
            style={{ display: "none" }}
            onChange={(e) => handleFile(e.target.files?.[0])}
          />
          <div className="csv-icon">📄</div>
          <div className="csv-text">
            {uploading ? "Uploading…" : "Drag & drop a CSV file here"}
          </div>
          <div className="csv-subtext">or click to browse</div>
        </label>

        {uploadResult && uploadResult.ok && (
          <div className="success-banner">
            Imported {uploadResult.flights_imported} flights.
            {uploadResult.warnings?.length > 0 &&
              ` ${uploadResult.warnings.length} warning(s) below.`}
          </div>
        )}

        {uploadResult && !uploadResult.ok && uploadResult.errors?.length > 0 && (
          <div className="error-list">
            <div className="error-list-title">
              {uploadResult.errors.length} error(s) — nothing was imported.
            </div>
            <ul>
              {uploadResult.errors.slice(0, 20).map((err, i) => (
                <li key={i}>{formatUploadError(err)}</li>
              ))}
            </ul>
            {uploadResult.errors.length > 20 && (
              <div className="hint small">…and {uploadResult.errors.length - 20} more.</div>
            )}
          </div>
        )}

        {uploadResult && uploadResult.warnings?.length > 0 && (
          <div className="warning-list">
            <div className="warning-list-title">Warnings</div>
            <ul>
              {uploadResult.warnings.map((w, i) => (
                <li key={i}>{formatUploadWarning(w)}</li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </div>
  );
}

export default Upload;