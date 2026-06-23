/*
Airport management page (full CRUD).

Sortable table of airport master data with add / edit / delete. Create and
edit use a modal form. Delete is a soft-delete and is refused by the backend
(409) if the airport is still referenced by flights or based aircraft; that
message is shown to the user. All writes go to /api/fleet/airports.
*/
import { useEffect, useMemo, useState } from "react";
import {
  getFleetAirports,
  createAirport,
  updateAirport,
  deleteAirport,
} from "../api/client";
import "./Management.css";

function emptyDraft() {
  return {
    iata_code: "",
    icao_code: "",
    name: "",
    city: "",
    latitude: "",
    longitude: "",
    min_turnaround_min: 45,
    is_operational: false,
  };
}

function errDetail(e, fallback) {
  return e?.response?.data?.detail || fallback;
}

function Airports() {
  const [airports, setAirports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [sort, setSort] = useState({ key: "iata_code", dir: "asc" });

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
      const rows = await getFleetAirports();
      setAirports(Array.isArray(rows) ? rows : []);
      setError(null);
    } catch (e) {
      setError("Could not load airports from backend.");
    } finally {
      setLoading(false);
    }
  }

  function sortVal(a, key) {
    switch (key) {
      case "iata_code":
        return a.iata_code || "";
      case "icao_code":
        return a.icao_code || "";
      case "name":
        return a.name || "";
      case "city":
        return a.city || "";
      case "latitude":
        return a.latitude ?? 0;
      case "longitude":
        return a.longitude ?? 0;
      case "min_turnaround_min":
        return a.min_turnaround_min ?? 0;
      case "is_operational":
        return a.is_operational ? 1 : 0;
      default:
        return 0;
    }
  }

  const sorted = useMemo(() => {
    const arr = [...airports];
    arr.sort((a, b) => {
      const va = sortVal(a, sort.key);
      const vb = sortVal(b, sort.key);
      const cmp = va < vb ? -1 : va > vb ? 1 : 0;
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [airports, sort]);

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

  function openAdd() {
    setDraft(emptyDraft());
    setFormError(null);
    setModal({ open: true, mode: "add" });
  }

  function openEdit(a) {
    setDraft({
      iata_code: a.iata_code,
      icao_code: a.icao_code || "",
      name: a.name || "",
      city: a.city || "",
      latitude: a.latitude ?? "",
      longitude: a.longitude ?? "",
      min_turnaround_min: a.min_turnaround_min ?? 45,
      is_operational: !!a.is_operational,
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
    if (modal.mode === "add" && !draft.iata_code.trim()) {
      setFormError("IATA code is required.");
      return;
    }
    if (!draft.name.trim()) {
      setFormError("Name is required.");
      return;
    }
    const lat = parseFloat(draft.latitude);
    const lon = parseFloat(draft.longitude);
    if (Number.isNaN(lat) || Number.isNaN(lon)) {
      setFormError("Latitude and longitude must be numbers.");
      return;
    }

    const common = {
      icao_code: draft.icao_code || null,
      name: draft.name.trim(),
      city: draft.city || null,
      latitude: lat,
      longitude: lon,
      min_turnaround_min: Number(draft.min_turnaround_min) || 45,
      is_operational: !!draft.is_operational,
    };

    try {
      setSaving(true);
      if (modal.mode === "add") {
        await createAirport({
          ...common,
          iata_code: draft.iata_code.trim().toUpperCase(),
        });
      } else {
        await updateAirport(draft.iata_code, common);
      }
      setModal({ open: false, mode: "add" });
      await load();
    } catch (e) {
      setFormError(errDetail(e, "Could not save the airport."));
    } finally {
      setSaving(false);
    }
  }

  async function remove(a) {
    if (!window.confirm(`Delete airport ${a.iata_code} (${a.name})?`)) return;
    try {
      await deleteAirport(a.iata_code);
      await load();
    } catch (e) {
      // Backend returns 409 with a clear reason if still referenced.
      setError(errDetail(e, "Could not delete the airport."));
    }
  }

  const opCount = airports.filter((a) => a.is_operational).length;

  const COLUMNS = [
    { key: "iata_code", label: "Code", sortable: true },
    { key: "icao_code", label: "ICAO", sortable: true },
    { key: "name", label: "Name", sortable: true },
    { key: "city", label: "City", sortable: true },
    { key: "latitude", label: "Lat", sortable: true, num: true },
    { key: "longitude", label: "Lon", sortable: true, num: true },
    {
      key: "min_turnaround_min",
      label: "Min turn (min)",
      sortable: true,
      num: true,
    },
    { key: "is_operational", label: "Operational", sortable: true },
    { key: "actions", label: "", sortable: false },
  ];

  return (
    <div className="mgmt">
      <header className="page-head">
        <div>
          <h2>Airports</h2>
          <p className="mgmt-subtitle">
            {airports.length} airports · {opCount} operational · click a column
            to sort
          </p>
        </div>
        <div className="head-actions">
          <button className="mgmt-btn mgmt-btn-primary" onClick={openAdd}>
            + Add airport
          </button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      {loading ? (
        <div className="mgmt-empty">Loading airports…</div>
      ) : airports.length === 0 ? (
        <div className="mgmt-empty">
          No airports yet. Add one to get started.
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
                      (c.num ? "num " : "") +
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
                <tr key={a.iata_code}>
                  <td>
                    <code>{a.iata_code}</code>
                  </td>
                  <td>
                    <code>{a.icao_code || "—"}</code>
                  </td>
                  <td>{a.name}</td>
                  <td>{a.city || "—"}</td>
                  <td className="num">{(a.latitude ?? 0).toFixed(4)}</td>
                  <td className="num">{(a.longitude ?? 0).toFixed(4)}</td>
                  <td className="num">{a.min_turnaround_min ?? "—"}</td>
                  <td>
                    {a.is_operational ? (
                      <span className="badge badge-green">operational</span>
                    ) : (
                      <span className="badge badge-grey">display-only</span>
                    )}
                  </td>
                  <td>
                    <div className="mgmt-actions">
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
              {modal.mode === "add" ? "Add airport" : `Edit ${draft.iata_code}`}
            </div>
            {formError && <div className="modal-error">{formError}</div>}

            <div className="form-grid2">
              <div className="form-row">
                <label>IATA code</label>
                <input
                  type="text"
                  value={draft.iata_code}
                  disabled={modal.mode === "edit"}
                  placeholder="IST"
                  onChange={(e) => setField("iata_code", e.target.value)}
                />
              </div>
              <div className="form-row">
                <label>ICAO code</label>
                <input
                  type="text"
                  value={draft.icao_code}
                  placeholder="LTFM"
                  onChange={(e) => setField("icao_code", e.target.value)}
                />
              </div>
            </div>
            <div className="form-row">
              <label>Name</label>
              <input
                type="text"
                value={draft.name}
                onChange={(e) => setField("name", e.target.value)}
              />
            </div>
            <div className="form-row">
              <label>City</label>
              <input
                type="text"
                value={draft.city}
                onChange={(e) => setField("city", e.target.value)}
              />
            </div>
            <div className="form-grid2">
              <div className="form-row">
                <label>Latitude</label>
                <input
                  type="number"
                  step="0.0001"
                  value={draft.latitude}
                  onChange={(e) => setField("latitude", e.target.value)}
                />
              </div>
              <div className="form-row">
                <label>Longitude</label>
                <input
                  type="number"
                  step="0.0001"
                  value={draft.longitude}
                  onChange={(e) => setField("longitude", e.target.value)}
                />
              </div>
            </div>
            <div className="form-grid2">
              <div className="form-row">
                <label>Min turnaround (min)</label>
                <input
                  type="number"
                  value={draft.min_turnaround_min}
                  onChange={(e) =>
                    setField("min_turnaround_min", e.target.value)
                  }
                />
              </div>
              <div className="form-row checkbox">
                <input
                  id="op"
                  type="checkbox"
                  checked={draft.is_operational}
                  onChange={(e) => setField("is_operational", e.target.checked)}
                />
                <label htmlFor="op">Operational</label>
              </div>
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

export default Airports;
