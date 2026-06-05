/*
  A single KPI card: large value on top, label below, optional accent
  color and trend hint.

  Used by the Dashboard to surface the headline metrics for a run.
*/

import "./KpiCard.css";

function KpiCard({ label, value, unit, accent }) {
  // accent: "blue" | "green" | "orange" | "red" - controls border color
  const className = `kpi-card kpi-${accent || "blue"}`;
  return (
    <div className={className}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">
        {value}
        {unit && <span className="kpi-unit">{unit}</span>}
      </div>
    </div>
  );
}

export default KpiCard;
