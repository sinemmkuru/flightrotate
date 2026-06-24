/*
  Authentication / role state (Zustand).

  Access-control only: we track WHO is logged in and their role so the UI can
  gate admin-only actions. The real enforcement is server-side (require_admin
  -> 403); this store just drives login state and button visibility.

  Persisted to localStorage so a page refresh keeps the session. Tokens are
  in-memory on the backend, so after a *server* restart the token becomes
  invalid and the next admin action returns 401 -> we log out (see client.js).
*/

import { create } from "zustand";

const STORAGE_KEY = "flightrotate.auth";

function loadInitial() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw); // { token, role }
  } catch {
    /* ignore corrupt storage */
  }
  return { token: null, role: null };
}

const initial = loadInitial();

const useAuthStore = create((set) => ({
  token: initial.token,
  role: initial.role,

  // True once a successful login has stored a token.
  // (derived via isAuthenticated() below to avoid stale duplication)

  setAuth: (token, role) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ token, role }));
    set({ token, role });
  },

  logout: () => {
    localStorage.removeItem(STORAGE_KEY);
    set({ token: null, role: null });
  },
}));

// Convenience selectors (use as useAuthStore(selectIsAdmin) etc.)
export const selectIsAuthenticated = (s) => Boolean(s.token);
export const selectIsAdmin = (s) => s.role === "admin";

export default useAuthStore;
