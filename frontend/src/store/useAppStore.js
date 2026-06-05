/*
  Global state for FlightRotate using Zustand.

  We keep this small on purpose: only state that crosses page boundaries
  belongs here. Page-local state stays in component useState hooks.

  Currently tracked:
    - currentRunId   : the run shown on the dashboard
    - isOptimizing   : whether an optimization request is in flight
    - lastError      : string of the most recent API error (for toasts)
*/

import { create } from "zustand";

const useAppStore = create((set) => ({
  currentRunId: null,
  isOptimizing: false,
  lastError: null,

  setCurrentRunId: (runId) => set({ currentRunId: runId }),
  setIsOptimizing: (flag) => set({ isOptimizing: flag }),
  setLastError: (msg) => set({ lastError: msg }),
  clearError: () => set({ lastError: null }),
}));

export default useAppStore;
