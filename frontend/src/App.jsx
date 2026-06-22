/*
  Top-level component: wires up routing and the shared layout.

  All pages render inside <Layout>, which provides the sidebar nav
  and header. Each route maps to a page component.
*/

import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Configure from "./pages/Configure";
import Upload from "./pages/Upload";
import Compare from "./pages/Compare";
import MapView from "./pages/MapView";
import Disruption from "./pages/Disruption";
import History from "./pages/History";

import "./App.css";

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/configure" element={<Configure />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/history" element={<History />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/map" element={<MapView />} />
          <Route path="/disruption" element={<Disruption />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
