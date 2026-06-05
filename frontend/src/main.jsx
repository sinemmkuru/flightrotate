/*
  Vite entry point: mounts the React app to the #root div in index.html.
  StrictMode is intentionally NOT used in dev because it double-invokes
  effects, which makes API call debugging noisy.
*/

import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./index.css";

createRoot(document.getElementById("root")).render(<App />);
