// src/components/transactions/Transactions.tsx
import React, { useState } from 'react';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { Box, Button, Typography, Tabs, Tab, Chip } from '@mui/material';
import { Add, History, HourglassEmpty, SwapHoriz } from '@mui/icons-material';
import { alpha } from '@mui/material/styles';
import { TOKENS } from '../../styles/theme';
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
      {/* Premium header */}
      <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Box sx={{
            width: 40, height: 40, borderRadius: '11px',
            bgcolor: alpha(TOKENS.blue, 0.1),
            display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          }}>
            <SwapHoriz sx={{ color: TOKENS.blue, fontSize: 20 }} />
          </Box>
          <Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="h4" fontWeight={800}>Transacciones</Typography>
            </Box>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.125 }}>
              Registro de operaciones de cambio
            </Typography>
          </Box>
        </Box>
        <Button
          variant="contained"
          startIcon={<Add />}
          onClick={() => setShowForm(true)}
          sx={{
            borderRadius: '20px',
            fontWeight: 700,
            background: `linear-gradient(135deg, ${TOKENS.blue} 0%, #1D4ED8 100%)`,
            boxShadow: `0 4px 14px ${alpha(TOKENS.blue, 0.35)}`,
            '&:hover': { boxShadow: `0 6px 20px ${alpha(TOKENS.blue, 0.45)}` },
          }}
        >
          Nueva Transacción
        </Button>
      </Box>

      {/* Tabs */}
      <Box sx={{
        borderBottom: `1px solid ${TOKENS.border}`,
        mb: 3,
        bgcolor: TOKENS.surface,
        borderRadius: '10px 10px 0 0',
        border: `1px solid ${TOKENS.border}`,
        overflow: 'hidden',
      }}>
        <Tabs
          value={currentTab === -1 ? 0 : currentTab}
          onChange={(_, v) => navigate(TABS[v].path)}
          sx={{ minHeight: 44, '& .MuiTabs-indicator': { height: 2 } }}
        >
          {TABS.map(t => (
            <Tab
              key={t.path}
              icon={React.cloneElement(t.icon, { sx: { fontSize: 16 } })}
              iconPosition="start"
              label={t.label}
              sx={{
                minHeight: 44, fontSize: '0.8125rem', fontWeight: 600,
                textTransform: 'none', px: 2.5,
                '& .MuiTab-iconWrapper': { mb: '0 !important', mr: 0.5 },
              }}
            />
          ))}
        </Tabs>
      </Box>

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