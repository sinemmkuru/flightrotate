/*
  Axios-based HTTP client for the FlightRotate backend.

  All API calls go through here so we have:
    - A single base URL configuration
    - Consistent error handling
    - Easy mocking later for tests

  The backend is expected to run on http://localhost:8000.
*/

import axios from "axios";

const API_BASE_URL = "http://localhost:8000/api";

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000, // 60s - long enough for a synchronous GA run
  headers: { "Content-Type": "application/json" },
});

// --- Optimization endpoints ---

export async function runOptimization(body) {
  // body shape: { algorithm, weights, parameters?, seed? }
  const res = await client.post("/optimize", body);
  return res.data;
}

export async function generateSample(body = { size: "medium" }) {
  const res = await client.post("/sample", body);
  return res.data;
}

// Compare two optimization runs.
export async function compareRuns(runAId, runBId) {
  const res = await client.post("/compare", {
    run_a_id: runAId,
    run_b_id: runBId,
  });

  return res.data;
}

// --- Analytics endpoints ---

export async function listRuns() {
  const res = await client.get("/runs");
  return res.data;
}

export async function getRun(runId) {
  const res = await client.get(`/runs/${runId}`);
  return res.data;
}

export async function getAssignments(runId) {
  const res = await client.get(`/runs/${runId}/assignments`);
  return res.data;
}

// Map view: all airports
export async function getAirports() {
  const res = await client.get("/airports");
  return res.data;
}

export default client;

// Upload a flight schedule CSV (multipart)
// Upload a flight schedule CSV (multipart). Uses fetch to avoid the axios
// instance's default application/json Content-Type clobbering the multipart boundary.
export async function uploadFlights(file) {
  const form = new FormData();
  form.append("file", file);
  const base = client.defaults.baseURL || "";
  const res = await fetch(`${base}/upload/flights`, {
    method: "POST",
    body: form,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error("Upload failed");
    err.response = { status: res.status, data };
    throw err;
  }
  return data;
}
// Upload an aircraft fleet CSV (multipart). Same fetch approach as uploadFlights.
export async function uploadAircraft(file) {
  const form = new FormData();
  form.append("file", file);
  const base = client.defaults.baseURL || "";
  const res = await fetch(`${base}/upload/aircraft`, {
    method: "POST",
    body: form,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error("Upload failed");
    err.response = { status: res.status, data };
    throw err;
  }
  return data;
}
// Data availability counts (for gating the optimize button).
export async function getStatus() {
  const res = await client.get("/status");
  return res.data; // { flights, aircraft, airports }
}

// Naive greedy baseline KPIs for the current data ("% vs naive" deltas).
export async function getBaseline() {
  const { data } = await client.get("/baseline");
  return data;
}
// Simulate a disruption (AOG / cancel) and get a before/after recovery report.
export async function disrupt(body) {
  const { data } = await client.post("/disrupt", body);
  return data;
}
