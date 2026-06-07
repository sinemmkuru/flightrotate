/*
  Shared layout: dark sidebar on the left, header on top, main content
  area on the right.

  The sidebar links use NavLink so the currently active page gets an
  "active" class for highlighting.
*/

import { NavLink } from "react-router-dom";
import "./Layout.css";

const NAV_ITEMS = [
  { path: "/dashboard", label: "Dashboard", icon: "📊" },
  { path: "/configure", label: "Configure", icon: "⚙️" },
  { path: "/upload", label: "Data Upload", icon: "📤" },
  { path: "/compare", label: "Compare", icon: "⚖️" },
];

function Layout({ children }) {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <h1>FlightRotate</h1>
          <p className="sidebar-subtitle">Aircraft Rotation Optimizer</p>
        </div>

        <nav className="sidebar-nav">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                isActive ? "nav-item active" : "nav-item"
              }
            >
              <span className="nav-icon">{item.icon}</span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <p>v0.1.0</p>
        </div>
      </aside>

      <main className="main-content">{children}</main>
    </div>
  );
}

export default Layout;
