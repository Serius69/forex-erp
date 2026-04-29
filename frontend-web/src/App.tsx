import React, { Suspense, lazy } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from '@mui/material/styles';
import { CssBaseline, CircularProgress, Box } from '@mui/material';
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider';
import { AdapterDateFns } from '@mui/x-date-pickers/AdapterDateFnsV3';
import { SnackbarProvider } from 'notistack';
import { GoogleOAuthProvider } from '@react-oauth/google';
import { es as esLocale } from 'date-fns/locale';

import { theme } from './styles/theme';
import { AuthProvider } from './contexts/AuthContext';
import { WebSocketProvider } from './contexts/WebSocketContext';
import PrivateRoute from './components/common/PrivateRoute';
import RoleRoute from './components/common/RoleRoute';
import MainLayout from './components/common/MainLayout';

const Login        = lazy(() => import('./components/auth/Login'));
const Signup       = lazy(() => import('./components/auth/Signup'));
const Dashboard    = lazy(() => import('./components/dashboard/Dashboard'));
const Transactions = lazy(() => import('./components/transactions/Transactions'));
const Inventory    = lazy(() => import('./components/inventory/Inventory'));
const Predictions  = lazy(() => import('./components/predictions/Predictions'));
const Reports      = lazy(() => import('./components/reports/Reports'));
const Settings     = lazy(() => import('./components/settings/Settings'));
const Customers    = lazy(() => import('./components/customers/Customers'));
const Rates        = lazy(() => import('./components/rates/Rates'));
const UserAdmin         = lazy(() => import('./components/admin/UserAdmin'));
const AuditLog          = lazy(() => import('./components/admin/AuditLog'));
const MaintenancePanel  = lazy(() => import('./components/admin/MaintenancePanel'));
const Tarjetas          = lazy(() => import('./components/tarjetas/Tarjetas'));
const Capital           = lazy(() => import('./components/capital/Capital'));
const Ganancias         = lazy(() => import('./components/ganancias/Ganancias'));
const ImportData        = lazy(() => import('./components/import/ImportData'));
const Analytics           = lazy(() => import('./components/analytics/Analytics'));
const BranchAnalytics     = lazy(() => import('./components/analytics/BranchAnalytics'));
const ExecutiveDashboard  = lazy(() => import('./components/executive/ExecutiveDashboard'));
const AlertasPage         = lazy(() => import('./components/alertas/AlertasPage'));
const DecisionesPage      = lazy(() => import('./components/decisiones/DecisionesPage'));
const AIInsights          = lazy(() => import('./components/ai/AIInsights'));
const CompanyManagement   = lazy(() => import('./components/admin/CompanyManagement'));

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';

const LoadingScreen = () => (
  <Box
    display="flex"
    flexDirection="column"
    alignItems="center"
    justifyContent="center"
    height="100vh"
    sx={{ bgcolor: '#0F172A', gap: 3 }}
  >
    {/* Logo mark */}
    <Box sx={{
      width: 56, height: 56, borderRadius: '16px',
      background: 'linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      boxShadow: '0 8px 32px rgba(37,99,235,0.45)',
      animation: 'app-logo-pulse 2s ease-in-out infinite',
    }}>
      <Box component="span" sx={{ fontSize: 28, color: 'white', fontWeight: 900, fontFamily: 'Inter, sans-serif', lineHeight: 1 }}>K</Box>
    </Box>

    {/* Brand name */}
    <Box sx={{ textAlign: 'center' }}>
      <Box component="span" sx={{ display: 'block', fontSize: '1.125rem', fontWeight: 800, color: 'white', fontFamily: 'Inter, sans-serif', letterSpacing: '-0.01em' }}>
        Kapitalya
      </Box>
      <Box component="span" sx={{ display: 'block', fontSize: '0.7rem', fontWeight: 600, color: 'rgba(255,255,255,0.35)', letterSpacing: '0.12em', textTransform: 'uppercase', mt: 0.5 }}>
        Sistema Financiero
      </Box>
    </Box>

    {/* Spinner */}
    <CircularProgress
      size={24}
      thickness={3}
      sx={{ color: 'rgba(37,99,235,0.8)', mt: 1 }}
    />

    <style>{`
      @keyframes app-logo-pulse {
        0%, 100% { transform: scale(1);    box-shadow: 0 8px 32px rgba(37,99,235,0.45); }
        50%       { transform: scale(1.05); box-shadow: 0 12px 40px rgba(37,99,235,0.6);  }
      }
    `}</style>
  </Box>
);

function App() {
  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
        <ThemeProvider theme={theme}>
          <LocalizationProvider dateAdapter={AdapterDateFns} adapterLocale={esLocale}>
            <SnackbarProvider maxSnack={3} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}>
              <CssBaseline />
              <Router>
                <AuthProvider>
                  <Suspense fallback={<LoadingScreen />}>
                    <Routes>
                      {/* Public auth routes */}
                      <Route path="/login"  element={<Login />} />
                      <Route path="/signup" element={<Signup />} />

                      {/* Protected app shell */}
                      <Route
                        path="/"
                        element={
                          <PrivateRoute>
                            <WebSocketProvider>
                              <MainLayout />
                            </WebSocketProvider>
                          </PrivateRoute>
                        }
                      >
                        <Route index element={<Navigate to="/dashboard" replace />} />

                        {/* All roles */}
                        <Route path="dashboard"      element={<Dashboard />} />
                        <Route path="transactions/*" element={<Transactions />} />
                        <Route path="customers/*"    element={<Customers />} />
                        <Route path="inventory/*"    element={<Inventory />} />
                        <Route path="rates/*"        element={<Rates />} />
                        <Route path="tarjetas"       element={<Tarjetas />} />
                        <Route path="settings/*"     element={<Settings />} />
                        <Route path="alertas"        element={<AlertasPage />} />

                        {/* Supervisor + Admin */}
                        <Route path="analytics"   element={<RoleRoute roles={['ADMIN','SUPERVISOR']}><Analytics /></RoleRoute>} />
                        <Route path="capital"     element={<RoleRoute roles={['ADMIN','SUPERVISOR']}><Capital /></RoleRoute>} />
                        <Route path="ganancias"   element={<RoleRoute roles={['ADMIN','SUPERVISOR']}><Ganancias /></RoleRoute>} />
                        <Route path="reports/*"   element={<RoleRoute roles={['ADMIN','SUPERVISOR']}><Reports /></RoleRoute>} />
                        <Route path="predictions" element={<RoleRoute roles={['ADMIN','SUPERVISOR']}><Predictions /></RoleRoute>} />
                        <Route path="decisiones"       element={<RoleRoute roles={['ADMIN','SUPERVISOR']}><DecisionesPage /></RoleRoute>} />
                        <Route path="ai-insights"      element={<RoleRoute roles={['ADMIN','SUPERVISOR']}><AIInsights /></RoleRoute>} />
                        <Route path="branch-analytics" element={<RoleRoute roles={['ADMIN','SUPERVISOR']}><BranchAnalytics /></RoleRoute>} />

                        {/* Admin only */}
                        <Route path="executive"         element={<RoleRoute roles={['ADMIN']}><ExecutiveDashboard /></RoleRoute>} />
                        <Route path="import"            element={<RoleRoute roles={['ADMIN']}><ImportData /></RoleRoute>} />
                        <Route path="admin/users"       element={<RoleRoute roles={['ADMIN']}><UserAdmin /></RoleRoute>} />
                        <Route path="admin/branches"    element={<RoleRoute roles={['ADMIN']}><BranchAnalytics /></RoleRoute>} />
                        <Route path="admin/company"     element={<RoleRoute roles={['ADMIN']}><CompanyManagement /></RoleRoute>} />
                        <Route path="admin/audit"       element={<RoleRoute roles={['ADMIN']}><AuditLog /></RoleRoute>} />
                        <Route path="admin/maintenance" element={<RoleRoute roles={['ADMIN']}><MaintenancePanel /></RoleRoute>} />
                      </Route>
                    </Routes>
                  </Suspense>
                </AuthProvider>
              </Router>
            </SnackbarProvider>
          </LocalizationProvider>
        </ThemeProvider>
    </GoogleOAuthProvider>
  );
}

export default App;
