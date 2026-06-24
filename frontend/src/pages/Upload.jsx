/*
  Data Upload page.

  Two paths to populate the database:
    1. Generate synthetic data - calls POST /api/sample with a size preset.
    2. Upload your own CSVs - two independent cards:
         - Flight schedule  -> POST /api/upload/flights
         - Aircraft fleet   -> POST /api/upload/aircraft
       Airports are fixed master data (Turkish domestic); each upload
       replaces only its own dataset and is validated row-by-row with
       structured error/warning feedback.

  We also show the current database state so the user knows whether
  there is anything to optimize.
*/

import { useEffect, useState } from "react";
import {
  generateSample,
  listRuns,
  uploadFlights,
  uploadAircraft,
} from "../api/client";
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
    case "invalid_date_format":
      return `Row ${err.row}: "${err.value}" in ${err.column} is not a valid YYYY-MM-DD date.`;
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
    case "duplicate_tail_number":
      return `Duplicate tail_number "${w.value}" on row(s) ${w.rows.join(", ")}.`;
    case "no_aircraft":
      return w.message;
    default:
      return JSON.stringify(w);
  }
}

function UploadCard({ title, columns, kind, state, onFile }) {
  const [dragOver, setDragOver] = useState(false);
  const { uploading, result, file } = state;
  const done = result?.ok;
  const failed = result && !result.ok;
  const merged = result?.mode === "merge";
  const count =
    kind === "flights" ? result?.flights_imported : result?.aircraft_imported;
  const unit = kind === "flights" ? "flights" : "aircraft";

  const cardCls =
    "card upload-card" +
    (done ? " upload-card-done" : failed ? " upload-card-error" : "");

  return (
    <section className={cardCls}>
      <div className="upload-card-head">
        <h3>{title}</h3>
        <span className="upload-badge">Required</span>
      </div>

      <label
        className={"csv-dropzone" + (dragOver ? " csv-dropzone-active" : "")}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          onFile(e.dataTransfer.files?.[0]);
        }}
      >
        <input
          type="file"
          accept=".csv"
          style={{ display: "none" }}
          onChange={(e) => onFile(e.target.files?.[0])}
        />
        <div className="csv-icon">{done ? "✅" : "📄"}</div>
        {uploading ? (
          <div className="csv-text">Uploading…</div>
        ) : done ? (
          <>
            <div className="csv-text">{file?.name}</div>
            <div className="csv-subtext">
              {merged
                ? `merged: +${result.added} new · ${result.updated} updated · ${result.removed} removed · ${result.unchanged} unchanged`
                : `${count} ${unit} imported`}
              {file ? ` · ${(file.size / 1024).toFixed(1)} KB` : ""} · click to
              replace
            </div>
          </>
        ) : (
          <>
            <div className="csv-text">Drop CSV here or click to browse</div>
            <div className="csv-subtext">Max 5 MB · .csv only</div>
          </>
        )}
      </label>

      <div className="csv-required">
        <span className="csv-required-label">Required columns:</span>
        {columns.map((c) => (
          <span key={c} className={"csv-chip" + (done ? " csv-chip-done" : "")}>
            {c}
          </span>
        ))}
      </div>

      {failed && result.errors?.length > 0 && (
        <div className="error-list">
          <div className="error-list-title">
            {result.errors.length} error(s) — nothing imported.
          </div>
          <ul>
            {result.errors.slice(0, 20).map((err, i) => (
              <li key={i}>{formatUploadError(err)}</li>
            ))}
          </ul>
          {result.errors.length > 20 && (
            <div className="hint small">
              …and {result.errors.length - 20} more.
            </div>
          )}
        </div>
      )}
      {result?.warnings?.length > 0 && (
        <div className="warning-list">
          <div className="warning-list-title">Warnings</div>
          <ul>
            {result.warnings.map((w, i) => (
              <li key={i}>{formatUploadWarning(w)}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

// Preview + validation summary of a successfully uploaded flight schedule.
// Parses the uploaded File client-side (display only); the authoritative
// validation already happened on the backend.
function FlightPreview({ file, flightsImported, fleetLoaded }) {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [airports, setAirports] = useState(0);
  const [overnight, setOvernight] = useState(0);

  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    file.text().then((text) => {
      if (cancelled) return;
      const lines = text
        .replace(/\r/g, "")
        .split("\n")
        .filter((l) => l.trim());
      if (lines.length < 2) return;
      const header = lines[0].split(",").map((h) => h.trim());
      const idx = (name) => header.indexOf(name);
      const get = (cols, name) => (cols[idx(name)] || "").trim();
      const ap = new Set();
      let onight = 0;
      const parsed = lines.slice(1).map((line) => {
        const cols = line.split(",");
        const o = get(cols, "origin").toUpperCase();
        const d = get(cols, "destination").toUpperCase();
        const dep = get(cols, "dep_time");
        const arr = get(cols, "arr_time");
        if (o) ap.add(o);
        if (d) ap.add(d);
        if (arr && dep && arr < dep) onight += 1; // zero-padded HH:MM compares lexically
        return {
          flight_id: get(cols, "flight_id"),
          origin: o,
          destination: d,
          dep_time: dep,
          arr_time: arr,
        };
      });
      setRows(parsed.slice(0, 5));
      setTotal(parsed.length);
      setAirports(ap.size);
      setOvernight(onight);
    });
    return () => {
      cancelled = true;
    };
  }, [file]);

  if (!file || rows.length === 0) return null;

  return (
    <section className="card preview-card">
      <div className="preview-head">
        <h3>Flight schedule preview</h3>
        <span className="preview-sub">
          first {rows.length} of {total} rows
        </span>
        <span className="preview-valid">✓ All rows valid</span>
      </div>

      <table className="preview-table">
        <thead>
          <tr>
            <th>flight_id</th>
            <th>origin</th>
            <th>destination</th>
            <th>dep_time</th>
            <th>arr_time</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{r.flight_id}</td>
              <td>{r.origin}</td>
              <td>{r.destination}</td>
              <td>{r.dep_time}</td>
              <td>{r.arr_time}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="validation-summary">
        <span className="vs-title">Data validation summary</span>
        <span className="vs-chip vs-good">{flightsImported} valid flights</span>
        <span className="vs-chip vs-good">{airports} unique airports</span>
        {overnight > 0 && (
          <span className="vs-chip vs-warn">
            {overnight} overnight flight{overnight > 1 ? "s" : ""}
          </span>
        )}
        <span className={"vs-chip " + (fleetLoaded ? "vs-good" : "vs-pending")}>
          {fleetLoaded ? "Fleet loaded" : "Fleet pending"}
        </span>
      </div>
    </section>
  );
}

function Upload() {
  const [selectedSize, setSelectedSize] = useState("medium");
  const [generating, setGenerating] = useState(false);
  const [lastGenerated, setLastGenerated] = useState(null);
  const [error, setError] = useState(null);
  // Flight-schedule upload mode: "replace" wipes the active plan; "merge"
  // upserts (add/update/remove-in-range) and keeps runs.
  const [flightMode, setFlightMode] = useState("replace");

  const [flightUpload, setFlightUpload] = useState({
    uploading: false,
    result: null,
    file: null,
  });
  const [aircraftUpload, setAircraftUpload] = useState({
    uploading: false,
    result: null,
    file: null,
  });

  // Reuse the backend's run list as a "is there data?" indicator.
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

  async function handleGenerate(force = false) {
    setGenerating(true);
    setError(null);
    setLastGenerated(null);
    try {
      const result = await generateSample({
        size: selectedSize,
        seed: 42,
        clear_existing: true,
        force,
      });
      setLastGenerated(result);
      setHasRuns(false); // new data, no runs yet
    } catch (err) {
      // Wipe protection: a published plan exists. Confirm, then force.
      if (err.response?.status === 409 && !force) {
        const detail = err.response?.data?.detail || "A published plan exists.";
        setGenerating(false);
        if (window.confirm(`${detail}\n\nProceed and delete it?`)) {
          return handleGenerate(true);
        }
        return;
      }
      console.error(err);
      const detail = err.response?.data?.detail || err.message;
      setError(`Generation failed: ${detail}`);
    } finally {
      setGenerating(false);
    }
  }

  async function doUpload(kind, file, force = false) {
    if (!file) return;
    const setState = kind === "flights" ? setFlightUpload : setAircraftUpload;
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setState({
        uploading: false,
        file,
        result: { ok: false, errors: [{ type: "not_csv" }], warnings: [] },
      });
      return;
    }
    setState({ uploading: true, file, result: null });
    try {
      const res =
        kind === "flights"
          ? await uploadFlights(file, force, flightMode)
          : await uploadAircraft(file, force);
      setState({ uploading: false, file, result: res });
    } catch (e) {
      // Wipe protection: a published plan exists. Confirm, then force.
      if (e?.response?.status === 409 && !force) {
        const detail = e.response?.data?.detail || "A published plan exists.";
        setState({ uploading: false, file, result: null });
        if (window.confirm(`${detail}\n\nProceed and delete it?`)) {
          return doUpload(kind, file, true);
        }
        return;
      }
      let detail = "Upload failed.";
      const d = e?.response?.data?.detail;
      if (typeof d === "string") detail = d;
      else if (Array.isArray(d) && d.length && d[0]?.msg)
        detail = d.map((x) => x.msg).join("; ");
      setState({
        uploading: false,
        file,
        result: {
          ok: false,
          errors: [{ type: "server_error", message: detail }],
          warnings: [],
        },
      });
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
          onClick={() => handleGenerate()}
          disabled={generating}
          className="btn btn-primary btn-large"
        >
          {generating ? "Generating..." : "Generate sample"}
        </button>
        <p className="hint center small">
          Existing flights and aircraft will be cleared first.
        </p>
      </section>

      {/* --- CSV upload (Flight schedule + Aircraft fleet) --- */}
      <div className="upload-intro">
        <h3>Upload CSV</h3>
        <p className="hint">
          Upload your own data. Airports are fixed (Turkish domestic). The fleet
          is global; flights load into the active plan.
        </p>
        <div className="flight-mode">
          <span className="flight-mode-label">Flight schedule:</span>
          <label>
            <input
              type="radio"
              name="flightmode"
              checked={flightMode === "replace"}
              onChange={() => setFlightMode("replace")}
            />{" "}
            Replace plan
          </label>
          <label>
            <input
              type="radio"
              name="flightmode"
              checked={flightMode === "merge"}
              onChange={() => setFlightMode("merge")}
            />{" "}
            Merge (add/update, keep runs)
          </label>
        </div>
      </div>
      <div className="upload-cards">
        <UploadCard
          title="Flight schedule"
          columns={[
            "flight_id",
            "origin",
            "destination",
            "dep_time",
            "arr_time",
          ]}
          kind="flights"
          state={flightUpload}
          onFile={(f) => doUpload("flights", f)}
        />
        <UploadCard
          title="Aircraft fleet"
          columns={[
            "tail_number",
            "base_airport",
            "available_from",
            "maintenance_due",
          ]}
          kind="aircraft"
          state={aircraftUpload}
          onFile={(f) => doUpload("aircraft", f)}
        />
      </div>

      {flightUpload.result?.ok && (
        <FlightPreview
          file={flightUpload.file}
          flightsImported={flightUpload.result.flights_imported}
          fleetLoaded={!!aircraftUpload.result?.ok}
        />
      )}
    </div>
  );
}

export default Upload;
