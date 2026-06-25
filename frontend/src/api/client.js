/*
  Axios-based HTTP client for the FlightRotate backend.

  All API calls go through here so we have:
    - A single base URL configuration
    - Consistent error handling
    - Easy mocking later for tests

  The backend is expected to run on http://localhost:8000.
*/

import axios from "axios";

import useAuthStore from "../store/useAuthStore";

const API_BASE_URL = "http://localhost:8000/api";

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000, // 60s - long enough for a synchronous GA run
  headers: { "Content-Type": "application/json" },
});

// Attach the bearer token (if logged in) to every request. Single choke point
// so individual API calls don't have to know about auth.
client.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// If the server rejects the token (401 = unknown/expired token, e.g. after a
// backend restart) log the user out so they re-authenticate. A 403 (viewer
// attempting an admin action) is left for the caller/UI to report.
client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response && err.response.status === 401) {
      useAuthStore.getState().logout();
    }
    return Promise.reject(err);
  }
);

// Exchange credentials for a bearer token + role. Caller stores them via the
// auth store. Throws on bad credentials (401).
export async function login(username, password) {
  const res = await client.post("/login", { username, password });
  return res.data; // { token, role }
}

// The bearer header for the raw fetch() uploads below (which bypass the axios
// instance and therefore its request interceptor).
function authHeader() {
  const token = useAuthStore.getState().token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// --- Optimization endpoints ---

export async function runOptimization(body) {
  // body shape: { algorithm, weights, parameters?, seed? }
  const res = await client.post("/optimize", body);
  return res.data;
}

// Start an optimization in the background; returns { job_id, status } at once.
export async function runOptimizationAsync(body) {
  const res = await client.post("/optimize/async", body);
  return res.data;
}

// Poll a background optimization job: { status, progress, run_id, message, error }.
export async function getOptimizeStatus(jobId) {
  const res = await client.get(`/optimize/status/${jobId}`);
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

// --- Plans (schedules) ---
export async function listPlans() {
  const res = await client.get("/plans");
  return res.data;
}
export async function createPlan(name) {
  const res = await client.post("/plans", { name });
  return res.data;
}
export async function activatePlan(id) {
  const res = await client.post(`/plans/${id}/activate`);
  return res.data;
}
export async function renamePlan(id, name) {
  const res = await client.put(`/plans/${id}`, { name });
  return res.data;
}
export async function deletePlan(id) {
  const res = await client.delete(`/plans/${id}`);
  return res.data;
}

// --- Plan of record (publish / unpublish) ---
export async function getPublishedPlan() {
  const res = await client.get("/published-plan");
  return res.data; // RunSummary or null
}
export async function publishRun(runId) {
  const res = await client.post(`/runs/${runId}/publish`);
  return res.data;
}
export async function unpublishRun(runId) {
  const res = await client.post(`/runs/${runId}/unpublish`);
  return res.data;
}

export async function getAssignments(runId) {
  const res = await client.get(`/runs/${runId}/assignments`);
  return res.data;
}

// Decision support: flights this run could not assign, each with a reason code
// (availability / location / capacity) and the recovery lever.
export async function getUnassigned(runId) {
  const res = await client.get(`/runs/${runId}/unassigned`);
  return res.data; // { summary: { total, by_reason }, flights: [...] }
}

// Lever A: how many extra aircraft, and where, to cover every flight (with an
// estimated wet-lease cost). Read-only what-if; re-solves with CP-SAT.
export async function getCapacitySuggestion() {
  const res = await client.get("/capacity-suggestion");
  return res.data;
}

// Lever B: recover uncovered flights by repositioning idle aircraft on empty
// ferry legs (at fuel cost), instead of adding fleet. Read-only what-if.
export async function getFerrySuggestion() {
  const res = await client.get("/ferry-suggestion");
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
export async function uploadFlights(file, force = false, mode = "replace") {
  const form = new FormData();
  form.append("file", file);
  const base = client.defaults.baseURL || "";
  const params = new URLSearchParams();
  if (force) params.set("force", "true");
  if (mode && mode !== "replace") params.set("mode", mode);
  const qs = params.toString();
  const res = await fetch(`${base}/upload/flights${qs ? `?${qs}` : ""}`, {
    method: "POST",
    headers: authHeader(),
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
export async function uploadAircraft(file, force = false) {
  const form = new FormData();
  form.append("file", file);
  const base = client.defaults.baseURL || "";
  const res = await fetch(`${base}/upload/aircraft${force ? "?force=true" : ""}`, {
    method: "POST",
    headers: authHeader(),
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
// --- Fleet endpoints ---
export async function getFleetAircraft() {
  const res = await client.get("/fleet/aircraft");
  return res.data;
}
export async function getFleetAirports() {
  const res = await client.get("/fleet/airports");
  return res.data;
}
export async function createAircraft(body) {
  const res = await client.post("/fleet/aircraft", body);
  return res.data;
}
export async function updateAircraft(tail, body) {
  const res = await client.put(`/fleet/aircraft/${tail}`, body);
  return res.data;
}
export async function deleteAircraft(tail) {
  const res = await client.delete(`/fleet/aircraft/${tail}`);
  return res.data;
}
export async function createAirport(body) {
  const res = await client.post("/fleet/airports", body);
  return res.data;
}
export async function updateAirport(code, body) {
  const res = await client.put(`/fleet/airports/${code}`, body);
  return res.data;
}
export async function deleteAirport(code) {
  const res = await client.delete(`/fleet/airports/${code}`);
  return res.data;
}
export async function getAirportLookup(iata) {
  const res = await client.get(`/fleet/airport-lookup/${iata}`);
  return res.data;
}
