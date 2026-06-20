/*
  Fuel & emissions helpers (display-only estimates).

  CO2 factor: 3.16 kg CO2 per kg of Jet A-1 burned. This is the standard
  ICAO / DEFRA emission factor for jet kerosene and is used throughout the
  aviation industry for fuel-to-CO2 conversion.

  Fuel breakdown: the optimizer's per-leg fuel is the OPTIMIZED (trip/cruise)
  burn. For operational context we also estimate taxi and reserve fuel using
  typical B737-800 flight-planning assumptions. These estimates are NOT part
  of the optimization objective and do not change any stored KPI; they are
  shown only to make the per-flight view realistic, the way professional
  flight-planning tools present a fuel breakdown.
*/

export const CO2_PER_KG_FUEL = 3.16; // kg CO2 / kg Jet A-1
export const TAXI_FUEL_KG = 250; // taxi-out + taxi-in per leg (~12 min)
export const CONTINGENCY_PCT = 0.05; // 5% of trip fuel (ICAO contingency)
export const FINAL_RESERVE_KG = 1100; // ~30 min holding reserve, B737-800

export function co2Kg(fuelKg) {
  return (fuelKg || 0) * CO2_PER_KG_FUEL;
}

// Given the optimized (trip) fuel for a leg, estimate the block-fuel parts.
export function fuelBreakdown(tripFuelKg) {
  const trip = tripFuelKg || 0;
  const taxi = TAXI_FUEL_KG;
  const reserve = CONTINGENCY_PCT * trip + FINAL_RESERVE_KG;
  const block = trip + taxi + reserve;
  return { trip, taxi, reserve, block };
}

export function fmtKg(kg) {
  return `${Math.round(kg || 0).toLocaleString()} kg`;
}

// CO2 shown in tonnes once it passes 1 t, otherwise kg.
export function fmtCo2(kg) {
  const v = kg || 0;
  if (v >= 1000) return `${(v / 1000).toFixed(1)} t`;
  return `${Math.round(v).toLocaleString()} kg`;
}
