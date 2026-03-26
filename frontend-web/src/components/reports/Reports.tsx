// src/components/reports/Reports.tsx
import React from 'react';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { Box, Typography, Paper, Tabs, Tab } from '@mui/material';
import { Assessment, History, Schedule } from '@mui/icons-material';
import ReportsMain      from './ReportsMain';
import ReportsHistory   from './ReportsHistory';
import ReportsScheduled from './ReportsScheduled';

const TABS = [
  { label: 'Generar',     path: '/reports',           icon: <Assessment /> },
  { label: 'Historial',   path: '/reports/history',   icon: <History /> },
  { label: 'Programados', path: '/reports/scheduled', icon: <Schedule /> },
];

const Reports: React.FC = () => {
  const navigate  = useNavigate();
  const location  = useLocation();

  const currentTab = TABS.findIndex(t =>
    t.path === '/reports'
      ? location.pathname === '/reports'
      : location.pathname.startsWith(t.path)
  );

  return (
    <Box>
      <Typography variant="h4" fontWeight="bold" mb={2}>Reportes</Typography>

      <Paper sx={{ mb: 3 }}>
        <Tabs
          value={currentTab === -1 ? 0 : currentTab}
          onChange={(_, v) => navigate(TABS[v].path)}
        >
          {TABS.map(t => (
            <Tab key={t.path} icon={t.icon} iconPosition="start" label={t.label} />
          ))}
        </Tabs>
      </Paper>

      <Routes>
        <Route index            element={<ReportsMain />} />
        <Route path="history"   element={<ReportsHistory />} />
        <Route path="scheduled" element={<ReportsScheduled />} />
      </Routes>
    </Box>
  );
};

export default Reports;