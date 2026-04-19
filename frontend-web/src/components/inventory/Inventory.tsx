import React from 'react';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { Box, Typography, Tabs, Tab } from '@mui/material';
import InventoryStock     from './InventoryStock';
import InventoryMovements from './InventoryMovements';
import InventoryTransfers from './InventoryTransfers';

const Inventory: React.FC = () => {
  const navigate  = useNavigate();
  const location  = useLocation();

  const tabs = [
    { label: 'Resumen',        path: '/inventory' },
    { label: 'Movimientos',    path: '/inventory/movements' },
    { label: 'Transferencias', path: '/inventory/transfers' },
  ];

  const currentTab = tabs.findIndex(t =>
    location.pathname === t.path ||
    (t.path !== '/inventory' && location.pathname.startsWith(t.path))
  );

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h4" fontWeight="bold">Inventario</Typography>
      </Box>

      <Tabs value={currentTab === -1 ? 0 : currentTab} sx={{ mb: 3 }}
        onChange={(_, v) => navigate(tabs[v].path)}>
        {tabs.map(t => <Tab key={t.path} label={t.label} />)}
      </Tabs>

      <Routes>
        <Route index            element={<InventoryStock />} />
        <Route path="movements" element={<InventoryMovements />} />
        <Route path="transfers" element={<InventoryTransfers />} />
      </Routes>
    </Box>
  );
};

export default Inventory;