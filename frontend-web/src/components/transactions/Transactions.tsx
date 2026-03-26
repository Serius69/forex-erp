import React, { useState, useRef } from 'react';
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { Box, Button, Typography, Tabs, Tab } from '@mui/material';
import { Add } from '@mui/icons-material';
import TransactionList    from './TransactionList';
import TransactionForm    from './TransactionForm';
import TransactionHistory from './TransactionHistory';
import TransactionPending from './TransactionPending';

const Transactions: React.FC = () => {
  const [showForm, setShowForm] = useState(false);
  const refreshRef              = useRef<(() => void) | null>(null);
  const navigate                = useNavigate();
  const location                = useLocation();

  const tabs = [
    { label: 'Transacciones',  path: '/transactions' },
    { label: 'Historial',      path: '/transactions/history' },
    { label: 'Pendientes',     path: '/transactions/pending' },
  ];

  const currentTab = tabs.findIndex(t =>
    t.path === location.pathname || location.pathname.startsWith(t.path + '/')
  );

  const handleSuccess = () => {
    setShowForm(false);
    refreshRef.current?.();
  };

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h4" fontWeight="bold">Transacciones</Typography>
        <Button variant="contained" startIcon={<Add />} onClick={() => setShowForm(true)}>
          Nueva Transacción
        </Button>
      </Box>

      <Tabs value={currentTab === -1 ? 0 : currentTab} sx={{ mb: 3 }}
        onChange={(_, v) => navigate(tabs[v].path)}>
        {tabs.map(t => <Tab key={t.path} label={t.label} />)}
      </Tabs>

      <Routes>
        <Route index            element={<TransactionList onRefreshRef={refreshRef} />} />
        <Route path="history"   element={<TransactionHistory />} />
        <Route path="pending"   element={<TransactionPending />} />
        <Route path="new"       element={<Navigate to="/transactions" replace />} />
      </Routes>

      <TransactionForm
        open={showForm}
        onClose={() => setShowForm(false)}
        onSuccess={handleSuccess}
      />
    </Box>
  );
};

export default Transactions;