/*
Fleet management page (full CRUD).

Sortable table of the aircraft fleet with add / edit / delete. Maintenance
dates are highlighted when due soon or overdue; status shows a colour badge.
Create and edit use a modal form; the base airport is a dropdown of existing
airports. Delete is a soft-delete (confirmed first). All writes go to the
backend fleet module (/api/fleet/aircraft).
*/
import { useEffect, useMemo, useState } from "react";
import {
  getFleetAircraft,
  getFleetAirports,
  createAircraft,
  updateAircraft,
  deleteAircraft,
} from "../api/client";
import useAuthStore, { selectIsAdmin } from "../store/useAuthStore";
import "./Management.css";

const DAY_MS = 1000 * 60 * 60 * 24;
const STATUSES = ["active", "maintenance", "grounded"];

// ISO datetime -> "YYYY-MM-DDTHH:MM" for <input type="datetime-local">.
function toLocalInput(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

function emptyDraft() {
  return {
    tail_number: "",
    aircraft_type: "B737-800",
    base_airport: "",
    available_from: "",
    maintenance_due: "",
    status: "active",
  };
}

function errDetail(e, fallback) {
  return e?.response?.data?.detail || fallback;
}

function Fleet() {
  const isAdmin = useAuthStore(selectIsAdmin);
  const [aircraft, setAircraft] = useState([]);
  const [airports, setAirports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [sort, setSort] = useState({ key: "tail_number", dir: "asc" });

  const [modal, setModal] = useState({ open: false, mode: "add" });
  const [draft, setDraft] = useState(emptyDraft());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState(null);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      setLoading(true);
      const [ac, ap] = await Promise.all([
        getFleetAircraft(),
        getFleetAirports(),
      ]);
      setAircraft(Array.isArray(ac) ? ac : []);
      setAirports(Array.isArray(ap) ? ap : []);
      setError(null);
    } catch (e) {
      setError("Could not load the fleet from backend.");
    } finally {
      setLoading(false);
    }
  }

  function sortVal(a, key) {
    switch (key) {
      case "tail_number":
        return a.tail_number || "";
      case "aircraft_type":
        return a.aircraft_type || "";
      case "base_airport":
        return a.base_airport || "";
      case "available_from":
        return a.available_from
          ? new Date(a.available_from).getTime()
          : -Infinity;
      case "maintenance_due":
        return a.maintenance_due
          ? new Date(a.maintenance_due).getTime()
          : -Infinity;
      case "status":
        return a.status || "";
      default:
        return 0;
    }
  }

  const sorted = useMemo(() => {
    const arr = [...aircraft];
    arr.sort((a, b) => {
      const va = sortVal(a, sort.key);
      const vb = sortVal(b, sort.key);
      const cmp = va < vb ? -1 : va > vb ? 1 : 0;
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [aircraft, sort]);

  function toggleSort(key) {
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" },
    );
  }
  function arrow(key) {
    if (sort.key !== key) return "";
    return sort.dir === "asc" ? " ▲" : " ▼";
  }

  function statusBadge(status) {
    const s = (status || "").toLowerCase();
    const cls =
      s === "active"
        ? "badge-green"
        : s === "maintenance"
          ? "badge-orange"
          : s === "grounded"
            ? "badge-red"
            : "badge-grey";
    return (
      <span className={`badge ${cls}`}>{(status || "—").toUpperCase()}</span>
    );
  }

  function maintenanceCell(due) {
    if (!due) return <span className="badge badge-grey">none</span>;
    const days = Math.floor((new Date(due) - Date.now()) / DAY_MS);
    const text = new Date(due).toLocaleDateString();
    if (days < 0) return <span className="due-over">{text} (overdue)</span>;
    if (days <= 7)
      return (
        <span className="due-soon">
          {text} ({days}d)
        </span>
      );
    return <span>{text}</span>;
  }

  function openAdd() {
    setDraft(emptyDraft());
    setFormError(null);
    setModal({ open: true, mode: "add" });
  }

  function openEdit(a) {
    setDraft({
      tail_number: a.tail_number,
      aircraft_type: a.aircraft_type || "B737-800",
      base_airport: a.base_airport || "",
      available_from: toLocalInput(a.available_from),
      maintenance_due: a.maintenance_due
        ? new Date(a.maintenance_due).toISOString().slice(0, 10)
        : "",
      status: a.status || "active",
    });
    setFormError(null);
    setModal({ open: true, mode: "edit" });
  }

  function closeModal() {
    if (saving) return;
    setModal({ open: false, mode: "add" });
  }

  function setField(k, v) {
    setDraft((d) => ({ ...d, [k]: v }));
  }

  async function save() {
    setFormError(null);
    if (modal.mode === "add" && !draft.tail_number.trim()) {
      setFormError("Tail number is required.");
      return;
    }
    if (!draft.base_airport) {
      setFormError("Base airport is required.");
      return;
    }
    if (!draft.available_from) {
      setFormError("Available-from time is required.");
      return;
    }

    const payload = {
      aircraft_type: draft.aircraft_type || "B737-800",
      base_airport: draft.base_airport,
      available_from: draft.available_from,
      maintenance_due: draft.maintenance_due || null,
      status: draft.status || "active",
    };

    try {
      setSaving(true);
      if (modal.mode === "add") {
        await createAircraft({
          ...payload,
          tail_number: draft.tail_number.trim().toUpperCase(),
        });
      } else {
        await updateAircraft(draft.tail_number, payload);
      }
      setModal({ open: false, mode: "add" });
      await load();
    } catch (e) {
      setFormError(errDetail(e, "Could not save the aircraft."));
    } finally {
      setSaving(false);
    }
  }

  async function remove(a) {
    if (
      !window.confirm(
        `Delete aircraft ${a.tail_number}? It will be removed from the active fleet.`,
      )
    ) {
      return;
    }
    try {
      await deleteAircraft(a.tail_number);
      await load();
    } catch (e) {
      setError(errDetail(e, "Could not delete the aircraft."));
    }
  }

  const activeCount = aircraft.filter(
    (a) => (a.status || "").toLowerCase() === "active",
  ).length;

  const COLUMNS = [
    { key: "tail_number", label: "Tail", sortable: true },
    { key: "aircraft_type", label: "Type", sortable: true },
    { key: "base_airport", label: "Base", sortable: true },
    { key: "available_from", label: "Available from", sortable: true },
    { key: "maintenance_due", label: "Maintenance due", sortable: true },
    { key: "status", label: "Status", sortable: true },
    { key: "actions", label: "", sortable: false },
  ];

  return (
    <div className="mgmt">
      <header className="page-head">
        <div>
          <h2>Fleet</h2>
          <p className="mgmt-subtitle">
            {aircraft.length} aircraft · {activeCount} active · click a column
            to sort
          </p>
        </div>
        <div className="head-actions">
          {isAdmin && (
            <button className="mgmt-btn mgmt-btn-primary" onClick={openAdd}>
              + Add aircraft
            </button>
          )}
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      {loading ? (
        <div className="mgmt-empty">Loading fleet…</div>
      ) : aircraft.length === 0 ? (
        <div className="mgmt-empty">
          No aircraft yet. Add one, or upload a fleet CSV from Data Upload.
        </div>
      ) : (
        <div className="mgmt-table-wrap">
          <table className="mgmt-table">
            <thead>
              <tr>
                {COLUMNS.map((c) => (
                  <th
                    key={c.key}
                    className={
                      (c.sortable ? "sortable " : "") +
                      (sort.key === c.key ? "sorted" : "")
                    }
                    onClick={c.sortable ? () => toggleSort(c.key) : undefined}
                  >
                    {c.label}
                    {c.sortable ? arrow(c.key) : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((a) => (
                <tr key={a.tail_number}>
                  <td>
                    <code>{a.tail_number}</code>
                  </td>
                  <td>{a.aircraft_type || "—"}</td>
                  <td>{a.base_airport}</td>
                  <td>
                    {a.available_from
                      ? new Date(a.available_from).toLocaleString()
                      : "—"}
                  </td>
                  <td>{maintenanceCell(a.maintenance_due)}</td>
                  <td>{statusBadge(a.status)}</td>
                  <td>
                    <div className="mgmt-actions">
                      {isAdmin ? (
                        <>
                          <button
                            className="mgmt-action"
                            onClick={() => openEdit(a)}
                          >
                            Edit
                          </button>
                          <button
                            className="mgmt-action danger"
                            onClick={() => remove(a)}
                          >
                            Delete
                          </button>
                        </>
                      ) : (
                        <span className="mgmt-readonly">—</span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modal.open && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              {modal.mode === "add"
                ? "Add aircraft"
                : `Edit ${draft.tail_number}`}
            </div>
            {formError && <div className="modal-error">{formError}</div>}

            <div className="form-row">
              <label>Tail number</label>
              <input
                type="text"
                value={draft.tail_number}
                disabled={modal.mode === "edit"}
                placeholder="TC-JAA"
                onChange={(e) => setField("tail_number", e.target.value)}
              />
            </div>
            <div className="form-row">
              <label>Aircraft type</label>
              <input
                type="text"
                value={draft.aircraft_type}
                onChange={(e) => setField("aircraft_type", e.target.value)}
              />
            </div>
            <div className="form-row">
              <label>Base airport</label>
              <select
                value={draft.base_airport}
                onChange={(e) => setField("base_airport", e.target.value)}
              >
                <option value="">— select —</option>
                {airports.map((ap) => (
                  <option key={ap.iata_code} value={ap.iata_code}>
                    {ap.iata_code} — {ap.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-grid2">
              <div className="form-row">
                <label>Available from</label>
                <input
                  type="datetime-local"
                  value={draft.available_from}
                  onChange={(e) => setField("available_from", e.target.value)}
                />
              </div>
              <div className="form-row">
                <label>Maintenance due</label>
                <input
                  type="date"
                  value={draft.maintenance_due}
                  onChange={(e) => setField("maintenance_due", e.target.value)}
                />
              </div>
            </div>
            <div className="form-row">
              <label>Status</label>
              <select
                value={draft.status}
                onChange={(e) => setField("status", e.target.value)}
              >
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>

            <div className="modal-foot">
              <button
                className="mgmt-btn"
                onClick={closeModal}
                disabled={saving}
              >
                Cancel
              </button>
              <button
                className="mgmt-btn mgmt-btn-primary"
                onClick={save}
                disabled={saving}
              >
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default Fleet;
