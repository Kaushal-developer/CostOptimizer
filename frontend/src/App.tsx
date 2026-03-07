import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/common/Layout';
import ProtectedRoute from './components/common/ProtectedRoute';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import ResourcesPage from './pages/ResourcesPage';
import ResourceDetailPage from './pages/ResourceDetailPage';
import RecommendationsPage from './pages/RecommendationsPage';
import CloudAccountsPage from './pages/CloudAccountsPage';
import MonitoringPage from './pages/MonitoringPage';
import CostExplorerPage from './pages/CostExplorerPage';
import SavingsPlansPage from './pages/SavingsPlansPage';
import BillingPage from './pages/BillingPage';
import SettingsPage from './pages/SettingsPage';
import CompliancePage from './pages/CompliancePage';
import SecurityPage from './pages/SecurityPage';
import BudgetsPage from './pages/BudgetsPage';
import ReservationAdvisorPage from './pages/ReservationAdvisorPage';
import LoadBalancingPage from './pages/LoadBalancingPage';
import ArchitectureAdvisorPage from './pages/ArchitectureAdvisorPage';

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<LoginPage isRegister />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/resources" element={<ResourcesPage />} />
          <Route path="/resources/:id" element={<ResourceDetailPage />} />
          <Route path="/monitoring" element={<MonitoringPage />} />
          <Route path="/cost-explorer" element={<CostExplorerPage />} />
          <Route path="/recommendations" element={<RecommendationsPage />} />
          <Route path="/savings-plans" element={<SavingsPlansPage />} />
          <Route path="/billing" element={<BillingPage />} />
          <Route path="/compliance" element={<CompliancePage />} />
          <Route path="/security" element={<SecurityPage />} />
          <Route path="/budgets" element={<BudgetsPage />} />
          <Route path="/reservation-advisor" element={<ReservationAdvisorPage />} />
          <Route path="/load-balancing" element={<LoadBalancingPage />} />
          <Route path="/architecture-advisor" element={<ArchitectureAdvisorPage />} />
          <Route path="/accounts" element={<CloudAccountsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
