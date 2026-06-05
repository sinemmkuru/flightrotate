/*
  Configure page: sliders for the three objective weights (coverage,
  idle, fuel) and inputs for GA hyperparameters. Settings here get
  passed as POST /api/optimize body when an optimization is launched.
*/

function Configure() {
  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>Configure Optimization</h2>
      <p style={{ color: "var(--text-secondary)" }}>
        Objective weights and GA hyperparameters will go here.
      </p>
    </div>
  );
}

export default Configure;
