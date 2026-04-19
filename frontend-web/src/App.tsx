import React, { Suspense, lazy } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from '@mui/material/styles';
import { CssBaseline, CircularProgress, Box } from '@mui/material';
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider';
import { AdapterDateFns } from '@mui/x-date-pickers/AdapterDateFnsV3';
import { SnackbarProvider } from 'notistack';
import { Provider } from 'react-redux';
import { es as esLocale } from 'date-fns/locale';

import { store } from './store';
import { theme } from './styles/theme';
import { AuthProvider } from './contexts/AuthContext';
import { WebSocketProvider } from './contexts/WebSocketContext';
import PrivateRoute from './components/common/PrivateRoute';
import MainLayout from './components/common/MainLayout';

const Login        = lazy(() => import('./components/auth/Login'));
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
const ExecutiveDashboard  = lazy(() => import('./components/executive/ExecutiveDashboard'));
const AlertasPage         = lazy(() => import('./components/alertas/AlertasPage'));
const DecisionesPage      = lazy(() => import('./components/decisiones/DecisionesPage'));

const LoadingScreen = () => (
  <Box display="flex" alignItems="center" justifyContent="center" height="100vh">
    <CircularProgress size={60} />
  </Box>
);

function App() {
  return (
    <Provider store={store}>
      <ThemeProvider theme={theme}>
        <LocalizationProvider dateAdapter={AdapterDateFns} adapterLocale={esLocale}>
          <SnackbarProvider maxSnack={3} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}>
            <CssBaseline />
            {/* ✅ Router envuelve AuthProvider */}
            <Router>
              <AuthProvider>
                <Suspense fallback={<LoadingScreen />}>
                  <Routes>
                    <Route path="/login" element={<Login />} />
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
                      <Route path="dashboard"      element={<Dashboard />} />
                      <Route path="transactions/*" element={<Transactions />} />
                      <Route path="inventory/*"    element={<Inventory />} />
                      <Route path="predictions"    element={<Predictions />} />
                      <Route path="reports/*"      element={<Reports />} />
                      <Route path="customers/*"    element={<Customers />} />
                      <Route path="settings/*"     element={<Settings />} />
                      <Route path="rates/*"      element={<Rates />} />
                      <Route path="admin/users"       element={<UserAdmin />} />
                      <Route path="admin/audit"       element={<AuditLog />} />
                      <Route path="admin/maintenance" element={<MaintenancePanel />} />
                      <Route path="tarjetas"     element={<Tarjetas />} />
                      <Route path="capital"      element={<Capital />} />
                      <Route path="ganancias"    element={<Ganancias />} />
                      <Route path="analytics"    element={<Analytics />} />
                      <Route path="executive"    element={<ExecutiveDashboard />} />
                      <Route path="import"       element={<ImportData />} />
                      <Route path="alertas"      element={<AlertasPage />} />
                      <Route path="decisiones"   element={<DecisionesPage />} />

                    </Route>
                  </Routes>
                </Suspense>
              </AuthProvider>
            </Router>
          </SnackbarProvider>
        </LocalizationProvider>
      </ThemeProvider>
    </Provider>
  );
}

export default App;