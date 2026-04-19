// src/components/transactions/Transactions.tsx
import React, { useState } from 'react';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { Box, Button, Typography, Tabs, Tab } from '@mui/material';
import { Add, History, HourglassEmpty } from '@mui/icons-material';
import TransactionHistory from './TransactionHistory';
import TransactionPending from './TransactionPending';
import TransactionForm    from './TransactionForm';

const TABS = [
  { label: 'Transacciones',  path: '/transactions',         icon: <History /> },
  { label: 'Pendientes',     path: '/transactions/pending',  icon: <HourglassEmpty /> },
];

const Transactions: React.FC = () => {
  const [showForm, setShowForm] = useState(false);
  const navigate  = useNavigate();
  const location  = useLocation();

  const currentTab = TABS.findIndex(t =>
    t.path === '/transactions'
      ? location.pathname === '/transactions'
      : location.pathname.startsWith(t.path)
  );

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h4" fontWeight="bold">Transacciones</Typography>
        <Button variant="contained" startIcon={<Add />} onClick={() => setShowForm(true)}>
          Nueva Transacción
        </Button>
      </Box>

      <Tabs value={currentTab === -1 ? 0 : currentTab} sx={{ mb: 3 }}
        onChange={(_, v) => navigate(TABS[v].path)}>
        {TABS.map(t => (
          <Tab key={t.path} icon={t.icon} iconPosition="start" label={t.label} />
        ))}
      </Tabs>

      <Routes>
        <Route index       element={<TransactionHistory />} />
        <Route path="history"  element={<TransactionHistory />} />
        <Route path="pending"  element={<TransactionPending />} />
      </Routes>

      <TransactionForm
        open={showForm}
        onClose={() => setShowForm(false)}
        onSuccess={() => setShowForm(false)}
      />
    </Box>
  );
};

export default Transactions;