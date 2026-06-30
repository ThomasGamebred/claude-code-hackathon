import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import SwampDashboard from "./pages/SwampDashboard";
import CustomerList from "./pages/CustomerList";
import GoldenRecord from "./pages/GoldenRecord";
import StewardshipQueue from "./pages/StewardshipQueue";
import LineageTrace from "./pages/LineageTrace";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<SwampDashboard />} />
        <Route path="/customers" element={<CustomerList />} />
        <Route path="/customers/:id" element={<GoldenRecord />} />
        <Route path="/review" element={<StewardshipQueue />} />
        <Route path="/lineage/:id" element={<LineageTrace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
