// src/components/reports/ReportsMain.tsx
import React, { useState } from 'react';
import {
  Box, Grid, Card, CardContent, CardActions,
  Button, Tabs, Tab, Paper, TextField, FormControl,
  InputLabel, Select, MenuItem, Chip, Alert,
  CircularProgress, Divider, Typography,
} from '@mui/material';
import {
  PictureAsPdf, TableChart, Assessment, Security,
  AccountBalance, TrendingUp, People, CompareArrows,
} from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import { api, downloadFile } from '../../services/api';

const ReportsMain: React.FC = () => {
  const [tab,       setTab]       = useState(0);
  const [loading,   setLoading]   = useState<string | null>(null);
  const [dateFrom,  setDateFrom]  = useState(
    new Date(new Date().getFullYear(), new Date().getMonth(), 1)
      .toISOString().split('T')[0]);
  const [dateTo,    setDateTo]    = useState(
    new Date().toISOString().split('T')[0]);
  const [year,      setYear]      = useState(new Date().getFullYear());
  const [month,     setMonth]     = useState(new Date().getMonth() + 1);
  const [topN,      setTopN]      = useState(20);
  const [daysAhead, setDaysAhead] = useState(30);
  const [period,    setPeriod]    = useState('daily');
  const { enqueueSnackbar }       = useSnackbar();

  const handleDownload = async (
    endpoint: string,
    filename: string,
    params:   object = {},
    fmt:      'excel' | 'pdf' = 'excel'
  ) => {
    const key = `${endpoint}-${fmt}`;
    setLoading(key);
    try {
      const res = await api.get(endpoint, {
        params:       { ...params, format: fmt },
        responseType: 'blob',
      });
      const ext = fmt === 'excel' ? 'xlsx' : 'pdf';
      downloadFile(res.data, `${filename}.${ext}`);
      enqueueSnackbar(`${filename} descargado`, { variant: 'success' });
    } catch {
      enqueueSnackbar('Error al generar reporte', { variant: 'error' });
    } finally {
      setLoading(null);
    }
  };

  const ReportCard = ({
    title, description, icon, onExcel, onPdf, loadingKey,
  }: {
    title:       string;
    description: string;
    icon:        React.ReactNode;
    onExcel:     () => void;
    onPdf:       () => void;
    loadingKey:  string;
  }) => (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ flexGrow: 1 }}>
        <Box display="flex" alignItems="center" gap={1} mb={1}>
          {icon}
          <Typography variant="h6">{title}</Typography>
        </Box>
        <Typography variant="body2" color="text.secondary">{description}</Typography>
      </CardContent>
      <Divider />
      <CardActions sx={{ p: 2, gap: 1 }}>
        <Button size="small" variant="outlined"
          startIcon={loading === `${loadingKey}-excel`
            ? <CircularProgress size={14} /> : <TableChart />}
          onClick={onExcel} disabled={!!loading}>
          Excel
        </Button>
        <Button size="small" variant="outlined" color="error"
          startIcon={loading === `${loadingKey}-pdf`
            ? <CircularProgress size={14} /> : <PictureAsPdf />}
          onClick={onPdf} disabled={!!loading}>
          PDF
        </Button>
      </CardActions>
    </Card>
  );

  return (
    <Box>
      <Paper sx={{ mb: 3 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)}>
          <Tab icon={<Security />}   iconPosition="start" label="ASFI / Regulatorios" />
          <Tab icon={<Assessment />} iconPosition="start" label="Gerenciales" />
        </Tabs>
      </Paper>

      {/* ── Tab 0: ASFI ── */}
      {tab === 0 && (
        <Box>
          <Alert severity="info" sx={{ mb: 3 }}>
            Reportes oficiales de cumplimiento regulatorio según normativa ASFI/SEPEC Bolivia.
          </Alert>

          <Paper sx={{ p: 2, mb: 3 }}>
            <Typography variant="subtitle1" fontWeight="bold" mb={2}>
              Período para RTE y Libro Diario
            </Typography>
            <Grid container spacing={2} alignItems="center">
              <Grid xs={12} sm={4}>
                <TextField fullWidth label="Año" type="number"
                  value={year} onChange={(e) => setYear(parseInt(e.target.value))} />
              </Grid>
              <Grid xs={12} sm={4}>
                <FormControl fullWidth>
                  <InputLabel>Mes</InputLabel>
                  <Select value={month}
                    onChange={(e) => setMonth(e.target.value as number)} label="Mes">
                    {['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                      'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
                      .map((m, i) => <MenuItem key={i+1} value={i+1}>{m}</MenuItem>)}
                  </Select>
                </FormControl>
              </Grid>
              <Grid xs={12} sm={4}>
                <Chip label={`${month}/${year}`} color="primary" />
              </Grid>
            </Grid>
          </Paper>

          <Grid container spacing={3}>
            <Grid xs={12} sm={6} md={4}>
              <ReportCard
                title="RTE — Transacciones en Efectivo"
                description="Registro de transacciones >= $1,000 USD equivalente para ASFI."
                icon={<AccountBalance color="primary" />}
                loadingKey={`rte-${year}-${month}`}
                onExcel={() => handleDownload(
                  '/reports/asfi/rte/download-excel/',
                  `RTE_${year}_${month.toString().padStart(2,'0')}`,
                  { year, month }, 'excel'
                )}
                onPdf={() => handleDownload(
                  '/reports/asfi/rte/download-pdf/',
                  `RTE_${year}_${month.toString().padStart(2,'0')}`,
                  { year, month }, 'pdf'
                )}
              />
            </Grid>

            <Grid xs={12} sm={6} md={4}>
              <ReportCard
                title="PEP — Personas Expuestas Políticamente"
                description="Listado completo del registro PEP para cumplimiento ASFI."
                icon={<People color="warning" />}
                loadingKey="pep"
                onExcel={() => handleDownload(
                  '/reports/asfi/pep/download-excel/',
                  `PEP_${new Date().toISOString().split('T')[0]}`,
                  {}, 'excel'
                )}
                onPdf={() => handleDownload(
                  '/reports/asfi/pep/download-pdf/',
                  `PEP_${new Date().toISOString().split('T')[0]}`,
                  {}, 'pdf'
                )}
              />
            </Grid>

            <Grid xs={12} sm={6} md={4}>
              <ReportCard
                title="Libro Diario de Operaciones"
                description="Registro diario de operaciones según ASFI Art. 14."
                icon={<Assessment color="info" />}
                loadingKey="daily-log"
                onExcel={async () => {
                  setLoading('daily-log-excel');
                  try {
                    await api.post('/reports/asfi/daily-log/generate/', {
                      date:      new Date().toISOString().split('T')[0],
                      branch_id: 1,
                    });
                    enqueueSnackbar('Libro diario generado', { variant: 'success' });
                  } catch {
                    enqueueSnackbar('Error al generar libro diario', { variant: 'error' });
                  } finally {
                    setLoading(null);
                  }
                }}
                onPdf={async () => {
                  setLoading('daily-log-pdf');
                  try {
                    await api.post('/reports/asfi/daily-log/generate/', {
                      date:      new Date().toISOString().split('T')[0],
                      branch_id: 1,
                    });
                    enqueueSnackbar('Libro diario generado', { variant: 'success' });
                  } catch {
                    enqueueSnackbar('Error', { variant: 'error' });
                  } finally {
                    setLoading(null);
                  }
                }}
              />
            </Grid>
          </Grid>
        </Box>
      )}

      {/* ── Tab 1: Gerenciales ── */}
      {tab === 1 && (
        <Box>
          <Paper sx={{ p: 2, mb: 3 }}>
            <Typography variant="subtitle1" fontWeight="bold" mb={2}>
              Período del Reporte
            </Typography>
            <Grid container spacing={2} alignItems="center">
              <Grid xs={12} sm={3}>
                <TextField fullWidth label="Fecha Desde" type="date"
                  value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
                  InputLabelProps={{ shrink: true }} />
              </Grid>
              <Grid xs={12} sm={3}>
                <TextField fullWidth label="Fecha Hasta" type="date"
                  value={dateTo} onChange={(e) => setDateTo(e.target.value)}
                  InputLabelProps={{ shrink: true }} />
              </Grid>
              <Grid xs={12} sm={2}>
                <FormControl fullWidth>
                  <InputLabel>Período P&G</InputLabel>
                  <Select value={period}
                    onChange={(e) => setPeriod(e.target.value)} label="Período P&G">
                    <MenuItem value="daily">Diario</MenuItem>
                    <MenuItem value="monthly">Mensual</MenuItem>
                  </Select>
                </FormControl>
              </Grid>
              <Grid xs={12} sm={2}>
                <TextField fullWidth label="Top N Clientes" type="number"
                  value={topN} onChange={(e) => setTopN(parseInt(e.target.value))}
                  inputProps={{ min: 5, max: 100 }} />
              </Grid>
              <Grid xs={12} sm={2}>
                <TextField fullWidth label="Días Proyección" type="number"
                  value={daysAhead} onChange={(e) => setDaysAhead(parseInt(e.target.value))}
                  inputProps={{ min: 7, max: 90 }} />
              </Grid>
            </Grid>
          </Paper>

          <Grid container spacing={3}>
            <Grid xs={12} sm={6} md={4}>
              <ReportCard
                title="P&G — Pérdidas y Ganancias"
                description={`Análisis detallado de ingresos, costos y utilidad. Período: ${period}.`}
                icon={<TrendingUp color="success" />}
                loadingKey="pnl"
                onExcel={() => handleDownload(
                  '/reports/management/pnl/',
                  `PnG_${dateFrom}_${dateTo}`,
                  { date_from: dateFrom, date_to: dateTo, period }, 'excel'
                )}
                onPdf={() => handleDownload(
                  '/reports/management/pnl/',
                  `PnG_${dateFrom}_${dateTo}`,
                  { date_from: dateFrom, date_to: dateTo, period }, 'pdf'
                )}
              />
            </Grid>

            <Grid xs={12} sm={6} md={4}>
              <ReportCard
                title="Rentabilidad por Divisa"
                description="Análisis de rentabilidad desglosado por divisa y sucursal."
                icon={<AccountBalance color="primary" />}
                loadingKey="profitability"
                onExcel={() => handleDownload(
                  '/reports/management/profitability/',
                  `Rentabilidad_${dateFrom}_${dateTo}`,
                  { date_from: dateFrom, date_to: dateTo }, 'excel'
                )}
                onPdf={() => handleDownload(
                  '/reports/management/profitability/',
                  `Rentabilidad_${dateFrom}_${dateTo}`,
                  { date_from: dateFrom, date_to: dateTo }, 'pdf'
                )}
              />
            </Grid>

            <Grid xs={12} sm={6} md={4}>
              <ReportCard
                title="Ranking de Clientes"
                description={`Top ${topN} clientes por volumen de operaciones.`}
                icon={<People color="info" />}
                loadingKey="ranking"
                onExcel={() => handleDownload(
                  '/reports/management/client-ranking/',
                  `RankingClientes_${dateFrom}_${dateTo}`,
                  { date_from: dateFrom, date_to: dateTo, top_n: topN }, 'excel'
                )}
                onPdf={() => handleDownload(
                  '/reports/management/client-ranking/',
                  `RankingClientes_${dateFrom}_${dateTo}`,
                  { date_from: dateFrom, date_to: dateTo, top_n: topN }, 'pdf'
                )}
              />
            </Grid>

            <Grid xs={12} sm={6} md={4}>
              <ReportCard
                title="Comparativo de Períodos"
                description="Comparación automática vs período anterior equivalente."
                icon={<CompareArrows color="secondary" />}
                loadingKey="comparative"
                onExcel={() => handleDownload(
                  '/reports/management/comparative/',
                  `Comparativo_${dateFrom}_${dateTo}`,
                  { date_from: dateFrom, date_to: dateTo }, 'excel'
                )}
                onPdf={() => handleDownload(
                  '/reports/management/comparative/',
                  `Comparativo_${dateFrom}_${dateTo}`,
                  { date_from: dateFrom, date_to: dateTo }, 'pdf'
                )}
              />
            </Grid>

            <Grid xs={12} sm={6} md={4}>
              <ReportCard
                title="Proyección de Flujo de Caja"
                description={`Proyección de ingresos y egresos a ${daysAhead} días.`}
                icon={<Assessment color="warning" />}
                loadingKey="cashflow"
                onExcel={() => handleDownload(
                  '/reports/management/cashflow/',
                  `FlujoCaja_${dateFrom}`,
                  { base_date: dateFrom, days_ahead: daysAhead }, 'excel'
                )}
                onPdf={() => handleDownload(
                  '/reports/management/cashflow/',
                  `FlujoCaja_${dateFrom}`,
                  { base_date: dateFrom, days_ahead: daysAhead }, 'pdf'
                )}
              />
            </Grid>
          </Grid>
        </Box>
      )}
    </Box>
  );
};

export default ReportsMain;