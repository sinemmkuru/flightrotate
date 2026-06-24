/*
  Login page. Rendered outside the main Layout (no sidebar) whenever there is
  no authenticated session. On success it stores the token + role and the app
  re-renders into the normal layout.

  Two fixed demo accounts (see backend api/auth.py):
    admin  / admin123   -> full access
    viewer / viewer123  -> read-only
*/

import { useState } from "react";

import { login } from "../api/client";
import useAuthStore from "../store/useAuthStore";
import "./Login.css";

function Login() {
  const setAuth = useAuthStore((s) => s.setAuth);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const { token, role } = await login(username.trim(), password);
      setAuth(token, role);
      // No navigate needed: App re-renders into the authed layout once the
      // store has a token (the default route is /dashboard).
    } catch (err) {
      const status = err?.response?.status;
      setError(
        status === 401
          ? "Kullanıcı adı veya parola hatalı."
          : "Giriş yapılamadı. Sunucu çalışıyor mu?"
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={handleSubmit}>
        <h1 className="login-brand">FlightRotate</h1>
        <p className="login-subtitle">Aircraft Rotation Optimizer</p>

        <label className="login-label">
          Kullanıcı adı
          <input
            className="login-input"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
            autoComplete="username"
          />
        </label>

        <label className="login-label">
          Parola
          <input
            className="login-input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </label>

        {error && <div className="login-error">{error}</div>}

        <button className="login-button" type="submit" disabled={busy}>
          {busy ? "Giriş yapılıyor…" : "Giriş yap"}
        </button>

        <div className="login-hint">
          <strong>admin</strong> / admin123 · tam yetki
          <br />
          <strong>viewer</strong> / viewer123 · salt görüntüleme
        </div>
      </form>
    </div>
  );
}

export default Login;
