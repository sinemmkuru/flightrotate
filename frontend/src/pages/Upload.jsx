/*
  Data Upload page: drag-and-drop or file picker for a CSV of flights,
  plus a "Generate sample" button that calls POST /api/sample.
*/

function Upload() {
  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>Data Upload</h2>
      <p style={{ color: "var(--text-secondary)" }}>
        File upload area and sample data generation controls.
      </p>
    </div>
  );
}

export default Upload;
