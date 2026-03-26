// src/components/predictions/Predictions.tsx
import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Grid, Card, CardContent, Paper, Tabs, Tab,
  FormControl, InputLabel, Select, MenuItem, Button, Chip,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  CircularProgress, Alert, Tooltip, IconButton, LinearProgress,
} from '@mui/material';
import {
  TrendingUp, TrendingDown, Refresh, Psychology,
  BarChart, CheckCircle, Warning, Info,
} from '@mui/icons-material';
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, Legend, ResponsiveContainer, ReferenceLine,
  ReferenceArea,
} from 'recharts';
import { format, parseISO } from 'date-fns';
import { es } from 'date-fns/locale';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';

// ── Tipos ─────────────────────────────────────────────────────────────────────
interface PredictionPoint {
  date:              string;
  rate:              number;
  buy_rate:          number;
  sell_rate:         number;
  confidence_lower:  number;
  confidence_upper:  number;
  confidence_score:  number;
}

interface PredictionsData {
  currency_pair:  string;
  predictions:    Record<string, PredictionPoint[]>;
  generated_at:   string;
}

interface ModelPerformance {
  model:            string;
  type:             string;
  currency_pair:    string;
  average_error:    number;
  predictions_count:number;
  metrics:          Record<string, any>;
}

interface AccuracyReport {
  [modelType: string]: {
    total_predictions:        number;
    average_error:            number;
    max_error:                number;
    min_error:                number;
    within_confidence_interval:number;
    confidence_accuracy:      number;
  };
}

// ── Colores por modelo ────────────────────────────────────────────────────────
const MODEL_COLORS: Record<string, string> = {
  PROPHET:  '#1976d2',
  LSTM:     '#9c27b0',
  ARIMA:    '#ff9800',
  ENSEMBLE: '#4caf50',
};

const CURRENCY_PAIRS = ['USD/BOB', 'EUR/BOB', 'BRL/BOB', 'ARS/BOB'];

// ── Tooltip personalizado ─────────────────────────────────────────────────────
const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <Paper sx={{ p: 1.5, minWidth: 180 }}>
      <Typography variant="caption" fontWeight="bold" display="block">
        {label}
      </Typography>
      {payload.map((p: any) => (
        <Box key={p.dataKey} display="flex" justifyContent="space-between" gap={2}>
          <Typography variant="caption" color={p.color}>{p.name}</Typography>
          <Typography variant="caption" fontWeight="bold">{p.value?.toFixed(4)}</Typography>
        </Box>
      ))}
    </Paper>
  );
};

// ── Componente principal ──────────────────────────────────────────────────────
const Predictions: React.FC = () => {
  const [tab,           setTab]           = useState(0);
  const [currencyPair,  setCurrencyPair]  = useState('USD/BOB');
  const [activeModels,  setActiveModels]  = useState<string[]>(['PROPHET','LSTM','ENSEMBLE']);
  const [predictions,   setPredictions]   = useState<PredictionsData | null>(null);
  const [performance,   setPerformance]   = useState<ModelPerformance[]>([]);
  const [accuracy,      setAccuracy]      = useState<AccuracyReport>({});
  const [models,        setModels]        = useState<any[]>([]);
  const [loading,       setLoading]       = useState(true);
  const [generating,    setGenerating]    = useState(false);
  const [training,      setTraining]      = useState(false);
  const { user }                          = useAuth();
  const { enqueueSnackbar }               = useSnackbar();

  const loadPredictions = useCallback(async () => {
    setLoading(true);
    try {
      const [predRes, perfRes, accRes, modRes] = await Promise.all([
        api.get('/predictions/predictions/current/', {
          params: { currency_pair: currencyPair },
        }),
        api.get('/predictions/models/performance/'),
        api.get('/predictions/predictions/accuracy-report/'),
        api.get('/predictions/models/'),
      ]);
      setPredictions(predRes.data);
      setPerformance(perfRes.data);
      setAccuracy(accRes.data);
      setModels(modRes.data.results ?? modRes.data);
    } catch (e) {
      enqueueSnackbar('Error al cargar predicciones', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [currencyPair, enqueueSnackbar]);

  useEffect(() => { loadPredictions(); }, [loadPredictions]);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      await api.post('/predictions/predictions/generate/', {
        currency_pair: currencyPair,
        horizon:       24,
      });
      enqueueSnackbar('Predicciones generadas', { variant: 'success' });
      loadPredictions();
    } catch {
      enqueueSnackbar('Error al generar predicciones', { variant: 'error' });
    } finally {
      setGenerating(false);
    }
  };

  const handleTrainAll = async () => {
    setTraining(true);
    try {
      await api.post('/predictions/models/train-all/');
      enqueueSnackbar('Entrenamiento iniciado en segundo plano', { variant: 'info' });
    } catch {
      enqueueSnackbar('Error al iniciar entrenamiento', { variant: 'error' });
    } finally {
      setTraining(false);
    }
  };

  // ── Preparar datos del gráfico ────────────────────────────────────────────
  const chartData = React.useMemo(() => {
    if (!predictions?.predictions) return [];

    // Unir todos los puntos por fecha
    const allDates = new Set<string>();
    Object.values(predictions.predictions).forEach((points) => {
      points.forEach((p) => allDates.add(p.date as string));
    });

    return Array.from(allDates).sort().map((dateStr) => {
      const point: any = {
        date: format(parseISO(dateStr as string), 'HH:mm', { locale: es }),
        full_date: dateStr,
      };
      Object.entries(predictions.predictions).forEach(([modelType, points]) => {
        const match = points.find((p) => p.date === dateStr);
        if (match) {
          point[`${modelType}_rate`]    = match.rate;
          point[`${modelType}_buy`]     = match.buy_rate;
          point[`${modelType}_sell`]    = match.sell_rate;
          point[`${modelType}_lower`]   = match.confidence_lower;
          point[`${modelType}_upper`]   = match.confidence_upper;
        }
      });
      return point;
    });
  }, [predictions]);

  // ── Obtener tasa actual del primer modelo ─────────────────────────────────
  const currentRate = React.useMemo(() => {
    if (!predictions?.predictions) return null;
    const firstModel = Object.values(predictions.predictions)[0];
    if (!firstModel?.length) return null;
    return firstModel[0];
  }, [predictions]);

  const modelKeys = predictions ? Object.keys(predictions.predictions) : [];

  if (loading) {
    return (
      <Box display="flex" flexDirection="column" alignItems="center"
           justifyContent="center" minHeight={400} gap={2}>
        <CircularProgress size={48} />
        <Typography color="text.secondary">Cargando predicciones ML...</Typography>
      </Box>
    );
  }

  return (
    <Box>
      {/* ── Header ── */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box display="flex" alignItems="center" gap={1}>
          <Psychology color="primary" sx={{ fontSize: 32 }} />
          <Typography variant="h4" fontWeight="bold">Predicciones ML</Typography>
        </Box>
        <Box display="flex" gap={1}>
          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel>Par de divisas</InputLabel>
            <Select value={currencyPair}
              onChange={(e) => setCurrencyPair(e.target.value)} label="Par de divisas">
              {CURRENCY_PAIRS.map((pair) => (
                <MenuItem key={pair} value={pair}>{pair}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <Button variant="outlined" startIcon={<Refresh />}
            onClick={loadPredictions} disabled={loading}>
            Actualizar
          </Button>
          <Button variant="outlined" color="secondary"
            startIcon={generating ? <CircularProgress size={16} /> : <TrendingUp />}
            onClick={handleGenerate} disabled={generating}>
            Generar
          </Button>
          {user?.role === 'ADMIN' && (
            <Button variant="contained" color="warning"
              startIcon={training ? <CircularProgress size={16} /> : <Psychology />}
              onClick={handleTrainAll} disabled={training}>
              Entrenar Modelos
            </Button>
          )}
        </Box>
      </Box>

      {/* ── KPI Cards ── */}
      <Grid container spacing={2} mb={3}>
        <Grid xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography variant="body2" color="text.secondary">Tasa Actual (USD/BOB)</Typography>
              <Typography variant="h4" color="primary.main" fontWeight="bold">
                {currentRate ? currentRate.rate.toFixed(4) : '—'}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Compra: {currentRate?.buy_rate.toFixed(4) ?? '—'} |
                Venta: {currentRate?.sell_rate.toFixed(4) ?? '—'}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography variant="body2" color="text.secondary">Modelos Activos</Typography>
              <Typography variant="h4" fontWeight="bold">
                {models.filter(m => m.is_active).length}
              </Typography>
              <Box display="flex" gap={0.5} mt={0.5} flexWrap="wrap">
                {Object.entries(MODEL_COLORS).map(([type, color]) => (
                  <Chip key={type} label={type} size="small"
                    sx={{ bgcolor: color, color: 'white', fontSize: 10 }} />
                ))}
              </Box>
            </CardContent>
          </Card>
        </Grid>
        <Grid xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography variant="body2" color="text.secondary">Mejor Precisión</Typography>
              {Object.entries(accuracy).length > 0 ? (() => {
                const best = Object.entries(accuracy)
                  .sort(([,a],[,b]) => a.average_error - b.average_error)[0];
                return best ? (
                  <>
                    <Typography variant="h4" color="success.main" fontWeight="bold">
                      {best[0]}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      Error promedio: {best[1].average_error.toFixed(2)}%
                    </Typography>
                  </>
                ) : null;
              })() : (
                <Typography variant="body2" color="text.secondary">Sin datos</Typography>
              )}
            </CardContent>
          </Card>
        </Grid>
        <Grid xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Typography variant="body2" color="text.secondary">Confianza Promedio</Typography>
              <Typography variant="h4" fontWeight="bold">
                {currentRate
                  ? `${(currentRate.confidence_score * 100).toFixed(0)}%`
                  : '—'}
              </Typography>
              {currentRate && (
                <LinearProgress
                  variant="determinate"
                  value={currentRate.confidence_score * 100}
                  color={currentRate.confidence_score > 0.7 ? 'success' :
                         currentRate.confidence_score > 0.4 ? 'warning' : 'error'}
                  sx={{ mt: 1, height: 6, borderRadius: 3 }}
                />
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* ── Tabs ── */}
      <Paper sx={{ mb: 3 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)}>
          <Tab icon={<TrendingUp />}  iconPosition="start" label="Predicciones" />
          <Tab icon={<BarChart />}    iconPosition="start" label="Precisión" />
          <Tab icon={<Psychology />}  iconPosition="start" label="Modelos" />
        </Tabs>
      </Paper>

      {/* ── Tab 0: Gráfico de predicciones ── */}
      {tab === 0 && (
        <Box>
          {/* Selector de modelos */}
          <Box display="flex" gap={1} mb={2} flexWrap="wrap">
            <Typography variant="body2" color="text.secondary" alignSelf="center">
              Modelos:
            </Typography>
            {Object.entries(MODEL_COLORS).map(([type, color]) => (
              <Chip
                key={type}
                label={type}
                size="small"
                onClick={() => setActiveModels(prev =>
                  prev.includes(type) ? prev.filter(m => m !== type) : [...prev, type]
                )}
                sx={{
                  bgcolor:    activeModels.includes(type) ? color : 'transparent',
                  color:      activeModels.includes(type) ? 'white' : color,
                  border:     `2px solid ${color}`,
                  fontWeight: 'bold',
                  cursor:     'pointer',
                }}
              />
            ))}
          </Box>

          {chartData.length === 0 ? (
            <Alert severity="info" sx={{ mb: 2 }}>
              No hay predicciones disponibles para {currencyPair}.
              Haz clic en "Generar" para crear nuevas predicciones.
            </Alert>
          ) : (
            <>
              {/* Gráfico de tasas predichas */}
              <Paper sx={{ p: 2, mb: 3 }}>
                <Typography variant="h6" mb={2}>
                  Predicción de Tasas — {currencyPair} (próximas 24h)
                </Typography>
                <ResponsiveContainer width="100%" height={350}>
                  <LineChart data={chartData} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                    <YAxis
                      domain={['auto', 'auto']}
                      tick={{ fontSize: 11 }}
                      tickFormatter={(v) => v.toFixed(3)}
                    />
                    <RTooltip content={<CustomTooltip />} />
                    <Legend />
                    {modelKeys
                      .filter(m => activeModels.includes(m))
                      .map((modelType) => (
                        <Line
                          key={modelType}
                          type="monotone"
                          dataKey={`${modelType}_rate`}
                          name={modelType}
                          stroke={MODEL_COLORS[modelType] ?? '#999'}
                          strokeWidth={2}
                          dot={false}
                          activeDot={{ r: 4 }}
                        />
                      ))}
                  </LineChart>
                </ResponsiveContainer>
              </Paper>

              {/* Gráfico de compra/venta con banda de confianza */}
              {modelKeys.length > 0 && activeModels.includes(modelKeys[0]) && (
                <Paper sx={{ p: 2, mb: 3 }}>
                  <Typography variant="h6" mb={2}>
                    Tasas de Compra / Venta con Intervalo de Confianza — {modelKeys[0]}
                  </Typography>
                  <ResponsiveContainer width="100%" height={300}>
                    <AreaChart data={chartData} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                      <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                      <YAxis
                        domain={['auto', 'auto']}
                        tick={{ fontSize: 11 }}
                        tickFormatter={(v) => v.toFixed(3)}
                      />
                      <RTooltip content={<CustomTooltip />} />
                      <Legend />
                      {/* Banda de confianza */}
                      <Area
                        type="monotone"
                        dataKey={`${modelKeys[0]}_upper`}
                        name="Límite Superior"
                        stroke="transparent"
                        fill={MODEL_COLORS[modelKeys[0]] ?? '#1976d2'}
                        fillOpacity={0.1}
                      />
                      <Area
                        type="monotone"
                        dataKey={`${modelKeys[0]}_lower`}
                        name="Límite Inferior"
                        stroke="transparent"
                        fill="white"
                        fillOpacity={1}
                      />
                      <Line
                        type="monotone"
                        dataKey={`${modelKeys[0]}_buy`}
                        name="Compra"
                        stroke="#4caf50"
                        strokeWidth={2}
                        dot={false}
                      />
                      <Line
                        type="monotone"
                        dataKey={`${modelKeys[0]}_sell`}
                        name="Venta"
                        stroke="#f44336"
                        strokeWidth={2}
                        dot={false}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </Paper>
              )}

              {/* Tabla de predicciones */}
              <Paper sx={{ p: 2 }}>
                <Typography variant="h6" mb={2}>Detalle de Predicciones</Typography>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Hora</TableCell>
                      {modelKeys.filter(m => activeModels.includes(m)).map(m => (
                        <React.Fragment key={m}>
                          <TableCell align="right" sx={{ color: MODEL_COLORS[m] }}>
                            {m} — Tasa
                          </TableCell>
                          <TableCell align="right" sx={{ color: MODEL_COLORS[m] }}>
                            Compra
                          </TableCell>
                          <TableCell align="right" sx={{ color: MODEL_COLORS[m] }}>
                            Venta
                          </TableCell>
                        </React.Fragment>
                      ))}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {chartData.slice(0, 12).map((row, i) => (
                      <TableRow key={i} hover>
                        <TableCell>{row.date}</TableCell>
                        {modelKeys.filter(m => activeModels.includes(m)).map(m => (
                          <React.Fragment key={m}>
                            <TableCell align="right" sx={{ fontFamily: 'monospace' }}>
                              {row[`${m}_rate`]?.toFixed(4) ?? '—'}
                            </TableCell>
                            <TableCell align="right" sx={{ color: 'success.main', fontFamily: 'monospace' }}>
                              {row[`${m}_buy`]?.toFixed(4) ?? '—'}
                            </TableCell>
                            <TableCell align="right" sx={{ color: 'error.main', fontFamily: 'monospace' }}>
                              {row[`${m}_sell`]?.toFixed(4) ?? '—'}
                            </TableCell>
                          </React.Fragment>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Paper>
            </>
          )}
        </Box>
      )}

      {/* ── Tab 1: Precisión de modelos ── */}
      {tab === 1 && (
        <Box>
          {Object.keys(accuracy).length === 0 ? (
            <Alert severity="info">
              No hay datos de precisión disponibles aún.
              Los modelos necesitan predicciones evaluadas contra tasas reales.
            </Alert>
          ) : (
            <Grid container spacing={3}>
              {Object.entries(accuracy).map(([modelType, data]) => (
                <Grid xs={12} md={6} lg={4} key={modelType}>
                  <Card>
                    <CardContent>
                      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
                        <Typography variant="h6" fontWeight="bold"
                          sx={{ color: MODEL_COLORS[modelType] }}>
                          {modelType}
                        </Typography>
                        <Chip
                          label={data.average_error < 1 ? 'Excelente' :
                                 data.average_error < 3 ? 'Bueno' : 'Mejorable'}
                          color={data.average_error < 1 ? 'success' :
                                 data.average_error < 3 ? 'warning' : 'error'}
                          size="small"
                        />
                      </Box>

                      {[
                        ['Total predicciones',  data.total_predictions, null],
                        ['Error promedio',       `${data.average_error.toFixed(2)}%`, null],
                        ['Error máximo',         `${data.max_error.toFixed(2)}%`, null],
                        ['Error mínimo',         `${data.min_error.toFixed(2)}%`, null],
                        ['Dentro del intervalo', data.within_confidence_interval, null],
                        ['Precisión confianza',  `${data.confidence_accuracy.toFixed(1)}%`, null],
                      ].map(([label, value]) => (
                        <Box key={label as string} display="flex" justifyContent="space-between"
                          py={0.5} borderBottom="1px solid" borderColor="divider">
                          <Typography variant="body2" color="text.secondary">{label as string}</Typography>
                          <Typography variant="body2" fontWeight="bold">{value as string}</Typography>
                        </Box>
                      ))}

                      <Box mt={2}>
                        <Typography variant="caption" color="text.secondary" display="block" mb={0.5}>
                          Precisión del intervalo de confianza
                        </Typography>
                        <LinearProgress
                          variant="determinate"
                          value={data.confidence_accuracy}
                          color={data.confidence_accuracy > 80 ? 'success' :
                                 data.confidence_accuracy > 60 ? 'warning' : 'error'}
                          sx={{ height: 8, borderRadius: 4 }}
                        />
                        <Typography variant="caption" color="text.secondary">
                          {data.confidence_accuracy.toFixed(1)}%
                        </Typography>
                      </Box>
                    </CardContent>
                  </Card>
                </Grid>
              ))}
            </Grid>
          )}
        </Box>
      )}

      {/* ── Tab 2: Gestión de modelos ── */}
      {tab === 2 && (
        <Box>
          {models.length === 0 ? (
            <Alert severity="info">
              No hay modelos entrenados. Haz clic en "Entrenar Modelos" para iniciar.
            </Alert>
          ) : (
            <TableContainer component={Paper}>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>Nombre</TableCell>
                    <TableCell>Tipo</TableCell>
                    <TableCell>Par</TableCell>
                    <TableCell>Estado</TableCell>
                    <TableCell>Último entrenamiento</TableCell>
                    <TableCell>Métricas</TableCell>
                    {user?.role === 'ADMIN' && <TableCell>Acciones</TableCell>}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {models.map((model) => (
                    <TableRow key={model.id} hover>
                      <TableCell>
                        <Typography fontWeight="bold">{model.name}</Typography>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={model.model_type}
                          size="small"
                          sx={{
                            bgcolor: MODEL_COLORS[model.model_type] ?? '#999',
                            color: 'white',
                          }}
                        />
                      </TableCell>
                      <TableCell>{model.currency_pair}</TableCell>
                      <TableCell>
                        <Chip
                          icon={model.is_active ? <CheckCircle /> : <Warning />}
                          label={model.is_active ? 'Activo' : 'Inactivo'}
                          color={model.is_active ? 'success' : 'default'}
                          size="small"
                        />
                      </TableCell>
                      <TableCell>
                        <Typography variant="caption">
                          {model.last_trained
                            ? format(parseISO(model.last_trained), 'dd/MM/yyyy HH:mm', { locale: es })
                            : 'Nunca'}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        {model.metrics && Object.keys(model.metrics).length > 0 ? (
                          <Tooltip title={JSON.stringify(model.metrics, null, 2)}>
                            <IconButton size="small"><Info /></IconButton>
                          </Tooltip>
                        ) : (
                          <Typography variant="caption" color="text.secondary">
                            Sin métricas
                          </Typography>
                        )}
                      </TableCell>
                      {user?.role === 'ADMIN' && (
                        <TableCell>
                          <Button
                            size="small"
                            variant="outlined"
                            color={model.is_active ? 'error' : 'success'}
                            onClick={async () => {
                              try {
                                await api.post(
                                  `/predictions/models/${model.id}/activate/`,
                                  { is_active: !model.is_active }
                                );
                                enqueueSnackbar(
                                  `Modelo ${model.is_active ? 'desactivado' : 'activado'}`,
                                  { variant: 'success' }
                                );
                                loadPredictions();
                              } catch {
                                enqueueSnackbar('Error', { variant: 'error' });
                              }
                            }}
                          >
                            {model.is_active ? 'Desactivar' : 'Activar'}
                          </Button>
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}

          {/* Performance de modelos */}
          {performance.length > 0 && (
            <Box mt={3}>
              <Typography variant="h6" mb={2}>Rendimiento Reciente (últimos 7 días)</Typography>
              <Grid container spacing={2}>
                {performance.map((p, i) => (
                  <Grid xs={12} sm={6} md={4} key={i}>
                    <Card variant="outlined">
                      <CardContent>
                        <Typography fontWeight="bold" color={MODEL_COLORS[p.type] ?? '#999'}>
                          {p.model} — {p.currency_pair}
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          Error promedio: {p.average_error?.toFixed(2) ?? '—'}%
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          Predicciones evaluadas: {p.predictions_count}
                        </Typography>
                      </CardContent>
                    </Card>
                  </Grid>
                ))}
              </Grid>
            </Box>
          )}
        </Box>
      )}
    </Box>
  );
};

export default Predictions;