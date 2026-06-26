/*
  Global state for FlightRotate using Zustand.

  We keep this small on purpose: only state that crosses page boundaries
  belongs here. Page-local state stays in component useState hooks.

  Currently tracked:
    - currentRunId   : the run shown on the dashboard
    - isOptimizing   : whether an optimization request is in flight
    - lastError      : string of the most recent API error (for toasts)
    - planRefreshKey : bumped whenever the active plan's data changes (a new
                       schedule loaded, a run completed, ...). The PlanSwitcher
                       watches it so its "X flights · Y runs" meta refreshes live
                       instead of going stale until a page reload.
*/

import { create } from "zustand";

const useAppStore = create((set) => ({
  currentRunId: null,
  isOptimizing: false,
  lastError: null,
  planRefreshKey: 0,

  setCurrentRunId: (runId) => set({ currentRunId: runId }),
  setIsOptimizing: (flag) => set({ isOptimizing: flag }),
  setLastError: (msg) => set({ lastError: msg }),
  clearError: () => set({ lastError: null }),
  // Signal that the active plan's flight/run counts may have changed.
  bumpPlanRefresh: () => set((s) => ({ planRefreshKey: s.planRefreshKey + 1 })),
}));

export default useAppStore;
