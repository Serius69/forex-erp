import React from 'react';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { Box, Typography, Tabs, Tab, Chip } from '@mui/material';
import {
  Inventory2, Timeline, SwapHoriz, CreditCard,
} from '@mui/icons-material';
import { alpha } from '@mui/material/styles';
import { TOKENS } from '../../styles/theme';
import InventoryStock     from './InventoryStock';
import InventoryMovements from './InventoryMovements';
import InventoryTransfers from './InventoryTransfers';
import InventoryCards     from './InventoryCards';

const TABS = [
  { label: 'Resumen',        path: '/inventory',            icon: <Inventory2 sx={{ fontSize: 16 }} /> },
  { label: 'Movimientos',    path: '/inventory/movements',  icon: <Timeline sx={{ fontSize: 16 }} /> },
  { label: 'Transferencias', path: '/inventory/transfers',  icon: <SwapHoriz sx={{ fontSize: 16 }} /> },
  { label: 'Tarjetas',       path: '/inventory/cards',      icon: <CreditCard sx={{ fontSize: 16 }} /> },
];

const Inventory: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const currentTab = TABS.findIndex(t =>
    location.pathname === t.path ||
    (t.path !== '/inventory' && location.pathname.startsWith(t.path))
  );
  const tabIndex = currentTab === -1 ? 0 : currentTab;

  return (
    <Box>
      {/* Page header */}
      <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Box sx={{
            width: 40, height: 40, borderRadius: '11px',
            bgcolor: alpha(TOKENS.blue, 0.1),
            display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          }}>
            <Inventory2 sx={{ color: TOKENS.blue, fontSize: 20 }} />
          </Box>
          <Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="h4" fontWeight={800}>Inventario</Typography>
              <Chip label="EN LÍNEA" size="small" color="success"
                sx={{ height: 20, fontSize: '0.6rem', fontWeight: 800 }} />
            </Box>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.125 }}>
              Control de stock, movimientos y transferencias por divisa
            </Typography>
          </Box>
        </Box>
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
          value={tabIndex}
          onChange={(_, v) => navigate(TABS[v].path)}
          sx={{
            minHeight: 44,
            '& .MuiTabs-indicator': { height: 2, borderRadius: 0 },
          }}
        >
          {TABS.map(t => (
            <Tab
              key={t.path}
              label={t.label}
              icon={t.icon}
              iconPosition="start"
              sx={{
                minHeight: 44,
                gap: 0.75,
                fontSize: '0.8125rem',
                fontWeight: 600,
                textTransform: 'none',
                px: 2.5,
                '& .MuiTab-iconWrapper': { mb: '0 !important', mr: 0.5 },
              }}
            />
          ))}
        </Tabs>
      </Box>

      <Routes>
        <Route index            element={<InventoryStock />} />
        <Route path="movements" element={<InventoryMovements />} />
        <Route path="transfers" element={<InventoryTransfers />} />
        <Route path="cards"     element={<InventoryCards />} />
      </Routes>
    </Box>
  );
};

export default Inventory;
