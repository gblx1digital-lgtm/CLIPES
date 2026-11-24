import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { EmptyState } from "./components/ui";
import AutomationsPage from "./pages/AutomationsPage";
import CategoriesPage from "./pages/CategoriesPage";
import ClipsPage from "./pages/ClipsPage";
import CreatorsPage from "./pages/CreatorsPage";
import DashboardPage from "./pages/DashboardPage";
import DiscoveryPage from "./pages/DiscoveryPage";
import EditorPage from "./pages/EditorPage";
import ExportsPage from "./pages/ExportsPage";
import SettingsPage from "./pages/SettingsPage";
import { Compass } from "lucide-react";

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/clipes" element={<ClipsPage />} />
        <Route path="/descoberta" element={<DiscoveryPage />} />
        <Route path="/criadores" element={<CreatorsPage />} />
        <Route path="/categorias" element={<CategoriesPage />} />
        <Route path="/editor" element={<EditorPage />} />
        <Route path="/exportacoes" element={<ExportsPage />} />
        <Route path="/automacoes" element={<AutomationsPage />} />
        <Route path="/configuracoes" element={<SettingsPage />} />
        <Route path="*" element={<div className="p-6"><EmptyState icon={<Compass size={16} />} title="Página não encontrada" /></div>} />
      </Routes>
    </AppShell>
  );
}
