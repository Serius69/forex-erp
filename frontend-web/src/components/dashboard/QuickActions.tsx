import React from 'react';
import { Card, CardContent, Typography, Button, Box } from '@mui/material';
import { SwapHoriz, Assessment, Inventory } from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';

const QuickActions: React.FC = () => {
  const navigate = useNavigate();
  return (
    <Card>
      <CardContent>
        <Typography variant="h6" mb={2}>Acciones Rápidas</Typography>
        <Box display="flex" gap={1} flexWrap="wrap">
          <Button variant="outlined" startIcon={<SwapHoriz />}
            onClick={() => navigate('/transactions')}>
            Nueva Transacción
          </Button>
          <Button variant="outlined" startIcon={<Assessment />}
            onClick={() => navigate('/reports')}>
            Reportes
          </Button>
          <Button variant="outlined" startIcon={<Inventory />}
            onClick={() => navigate('/inventory')}>
            Inventario
          </Button>
        </Box>
      </CardContent>
    </Card>
  );
};

export default QuickActions;