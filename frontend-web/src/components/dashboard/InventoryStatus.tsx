import React from 'react';
import { Card, CardContent, Typography } from '@mui/material';

const InventoryStatus: React.FC = () => (
  <Card>
    <CardContent>
      <Typography variant="h6">Estado del Inventario</Typography>
      <Typography color="text.secondary">Cargando...</Typography>
    </CardContent>
  </Card>
);

export default InventoryStatus;