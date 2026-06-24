/*
  Plan switcher for the sidebar.

  A Plan is a named schedule that owns its own flights and runs; exactly one is
  active and the whole app operates on it. Switching, creating or deleting a
  plan reloads the page so every view reflects the newly active plan (the
  backend scopes all data to it server-side).
*/
import { useEffect, useState } from "react";
import {
  listPlans,
  createPlan,
  activatePlan,
  renamePlan,
  deletePlan,
} from "../api/client";
import "./PlanSwitcher.css";

function PlanSwitcher() {
  const [plans, setPlans] = useState([]);
  const [error, setError] = useState(false);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      setPlans(await listPlans());
      setError(false);
    } catch {
      setError(true);
    }
  }

  const active = plans.find((p) => p.is_active) || null;

  async function onSwitch(e) {
    const id = Number(e.target.value);
    if (active && id === active.id) return;
    await activatePlan(id);
    window.location.reload();
  }

  async function onNew() {
    const name = window.prompt("Name for the new plan:", "New plan");
    if (!name) return;
    await createPlan(name.trim());
    window.location.reload();
  }

  async function onRename() {
    if (!active) return;
    const name = window.prompt("Rename plan:", active.name);
    if (!name || name.trim() === active.name) return;
    await renamePlan(active.id, name.trim());
    await load();
  }

  async function onDelete() {
    if (!active) return;
    if (
      !window.confirm(
        `Delete plan "${active.name}"? Its schedule and runs will no longer be accessible.`,
      )
    )
      return;
    await deletePlan(active.id);
    window.location.reload();
  }

  if (error) return null; // backend down: keep the sidebar usable

  return (
    <div className="plan-switcher">
      <div className="ps-label">Plan</div>
      <select
        className="ps-select"
        value={active ? active.id : ""}
        onChange={onSwitch}
      >
        {plans.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      {active && (
        <div className="ps-meta">
          {active.flights} flights · {active.runs} run{active.runs === 1 ? "" : "s"}
        </div>
      )}
      <div className="ps-actions">
        <button onClick={onNew} title="New plan">
          ＋ New
        </button>
        <button onClick={onRename} title="Rename" disabled={!active}>
          Rename
        </button>
        <button onClick={onDelete} title="Delete" disabled={!active || plans.length <= 1}>
          Delete
        </button>
      </div>
    </div>
  );
}

export default PlanSwitcher;
