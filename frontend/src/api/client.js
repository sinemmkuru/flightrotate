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

export default client;
