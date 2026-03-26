import React, { useState } from 'react';
import {
  Box, Paper, Typography, Grid, Card, CardContent,
  CardActions, Button, Switch, FormControlLabel,
  List, ListItem, ListItemText, ListItemSecondaryAction,
  Chip, Divider, Alert,
} from '@mui/material';
import { Schedule, Add } from '@mui/icons-material';
import { useAuth } from '../../contexts/AuthContext';

const SCHEDULED_REPORTS = [
  {
    id: 1, name: 'RTE Mensual ASFI',
    description: 'Registro de Transacciones en Efectivo',
    schedule: 'Primer día de cada mes', active: true,
    type: 'ASFI', nextRun: '01/04/2026',
  },
  {
    id: 2, name: 'Libro Diario',
    description: 'Libro diario de operaciones ASFI Art. 14',
    schedule: 'Diariamente a las 23:55', active: true,
    type: 'ASFI', nextRun: '26/03/2026',
  },
  {
    id: 3, name: 'P&G Semanal',
    description: 'Informe de pérdidas y ganancias semanal',
    schedule: 'Lunes a las 08:00', active: false,
    type: 'GERENCIAL', nextRun: '30/03/2026',
  },
  {
    id: 4, name: 'Ranking de Clientes',
    description: 'Top 20 clientes por volumen mensual',
    schedule: 'Último día del mes', active: true,
    type: 'GERENCIAL', nextRun: '31/03/2026',
  },
];

const ReportsScheduled: React.FC = () => {
  const [reports, setReports] = useState(SCHEDULED_REPORTS);
  const { user }              = useAuth();

  const toggleReport = (id: number) => {
    setReports(prev => prev.map(r =>
      r.id === id ? { ...r, active: !r.active } : r
    ));
  };

  return (
    <Box>
      <Alert severity="info" sx={{ mb: 3 }}>
        Los reportes programados se generan automáticamente y se guardan en el historial.
        Requiere que Celery Beat esté ejecutándose.
      </Alert>

      {user?.role !== 'ADMIN' && (
        <Alert severity="warning" sx={{ mb: 3 }}>
          Solo administradores pueden modificar reportes programados.
        </Alert>
      )}

      <Grid container spacing={2}>
        {['ASFI', 'GERENCIAL'].map((tipo) => (
          <Grid xs={12} md={6} key={tipo}>
            <Paper sx={{ p: 2 }}>
              <Typography variant="h6" mb={2} color="primary">
                Reportes {tipo}
              </Typography>
              <List disablePadding>
                {reports.filter(r => r.type === tipo).map((r, i, arr) => (
                  <React.Fragment key={r.id}>
                    <ListItem sx={{ px: 0 }}>
                      <ListItemText
                        primary={
                          <Box display="flex" alignItems="center" gap={1}>
                            {r.name}
                            <Chip
                              label={r.active ? 'Activo' : 'Inactivo'}
                              color={r.active ? 'success' : 'default'}
                              size="small"
                            />
                          </Box>
                        }
                        secondary={
                          <Box>
                            <Typography variant="caption" display="block">
                              {r.description}
                            </Typography>
                            <Typography variant="caption" color="primary" display="block">
                              <Schedule sx={{ fontSize: 12, mr: 0.5 }} />
                              {r.schedule} | Próxima: {r.nextRun}
                            </Typography>
                          </Box>
                        }
                      />
                      <ListItemSecondaryAction>
                        <Switch
                          checked={r.active}
                          onChange={() => toggleReport(r.id)}
                          disabled={user?.role !== 'ADMIN'}
                          size="small"
                        />
                      </ListItemSecondaryAction>
                    </ListItem>
                    {i < arr.length - 1 && <Divider />}
                  </React.Fragment>
                ))}
              </List>
            </Paper>
          </Grid>
        ))}
      </Grid>

      {user?.role === 'ADMIN' && (
        <Box mt={3} display="flex" justifyContent="flex-end">
          <Button variant="contained" startIcon={<Add />} disabled>
            Agregar Reporte Programado (próximamente)
          </Button>
        </Box>
      )}
    </Box>
  );
};

export default ReportsScheduled;