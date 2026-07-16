import React, { useState, useEffect } from 'react';
import {
  Card,
  CardContent,
  Typography,
  Box,
  ToggleButton,
  ToggleButtonGroup,
  CircularProgress,
  Alert,
  Chip,
  Grid,
  IconButton,
  Tooltip,
  FormControl,
  Select,
  MenuItem,
} from '@mui/material';
import {
  TrendingUp,
  ShowChart,
  Timeline,
  Refresh,
  Info,
} from '@mui/icons-material';
import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RTooltip,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';

import { api } from '../../services/api';
import { useWebSocket } from '../../contexts/WebSocketContext';
import { formatRate, formatNumber } from '../../utils/formatters';

interface PredictionData {
  date: string;
  rate: number;
  buy_rate: number;
  sell_rate: number;
  confidence_lower: number;
  confidence_upper: number;
  confidence_score: number;
}

const PredictionsChart: React.FC = () => {
  const [predictions, setPredictions] = useState<Record<string, PredictionData[]>>({});
  const [modelMape, setModelMape] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [selectedCurrency, setSelectedCurrency] = useState('USD');
  const [selectedModel, setSelectedModel] = useState('ENSEMBLE');
  const [viewType, setViewType] = useState<'rate' | 'buy_sell'>('rate');
  const { rates } = useWebSocket();

  useEffect(() => {
    loadPredictions();
  }, [selectedCurrency]);

  const loadPredictions = async () => {
    setLoading(true);
    try {
      const [predRes, modelsRes] = await Promise.allSettled([
        api.get('/predictions/predictions/current/', {
          params: { currency_pair: `${selectedCurrency}/BOB` },
        }),
        api.get('/predictions/models/', {
          params: { currency_pair: `${selectedCurrency}/BOB` },
        }),
      ]);
      if (predRes.status === 'fulfilled') {
        setPredictions(predRes.value.data.predictions);
      }
      // MAPE REAL por modelo (serie web) — nada de precisiones inventadas
      if (modelsRes.status === 'fulfilled') {
        const raw = modelsRes.value.data;
        const items: any[] = raw?.results ?? raw ?? [];
        const mape: Record<string, number> = {};
        (Array.isArray(items) ? items : []).forEach((m: any) => {
          if (m.market && m.market !== 'web') return;
          const v = m.metrics?.mape;
          if (typeof v === 'number' && v > 0 && mape[m.model_type] === undefined) {
            mape[m.model_type] = v;
          }
        });
        setModelMape(mape);
      }
    } catch (error) {
      console.error('Error loading predictions:', error);
    } finally {
      setLoading(false);
    }
  };

  // Serie plana para recharts: una fila por período con la predicción, la banda
  // de confianza (rango [inferior, superior]) y las tasas de compra/venta.
  // Se deduplica por hora (puede haber varias predicciones cacheadas para el
  // mismo período → antes el eje mostraba "13:00 13:00 14:00 14:00…"); gana
  // la más reciente de cada etiqueta.
  const chartData = React.useMemo(() => {
    const modelPredictions = predictions[selectedModel] || [];
    const byLabel = new Map<string, any>();
    modelPredictions.forEach((p) => {
      const label = format(new Date(p.date), 'HH:mm', { locale: es });
      byLabel.set(label, {
        label,
        rate: p.rate,
        buy_rate: p.buy_rate,
        sell_rate: p.sell_rate,
        band: [p.confidence_lower, p.confidence_upper] as [number, number],
      });
    });
    return Array.from(byLabel.values());
  }, [predictions, selectedModel]);

  const currentRate = rates[selectedCurrency]?.official;

  const tooltipFormatter = (value: any, name: any) => {
    if (Array.isArray(value)) {
      return [`Bs. ${formatRate(value[0])} – ${formatRate(value[1])}`, name];
    }
    return [`Bs. ${formatRate(value)}`, name];
  };

  const getModelInfo = () => {
    const modelInfo = {
      PROPHET:  { name: 'Prophet',  description: 'Modelo de series temporales de Facebook' },
      LSTM:     { name: 'LSTM',     description: 'Red neuronal de memoria a largo plazo' },
      ENSEMBLE: { name: 'Ensemble', description: 'Combinación de múltiples modelos' },
    };
    const base = modelInfo[selectedModel as keyof typeof modelInfo];
    if (!base) return undefined;
    // Precisión REAL desde metrics.mape del modelo entrenado (antes eran
    // porcentajes hardcodeados 92/89/94% que no salían de ningún dato).
    const mape = modelMape[selectedModel];
    const accuracy = typeof mape === 'number' && mape < 100
      ? `MAPE ${mape.toFixed(1)}%`
      : null;
    return { ...base, accuracy };
  };

  if (loading) {
    return (
      <Card>
        <CardContent>
          <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
            <CircularProgress />
          </Box>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 3 }}>
          <Typography variant="h6">Predicciones de Tasas de Cambio</Typography>
          <Box sx={{ display: 'flex', gap: 2, alignItems: 'center' }}>
            <FormControl size="small">
              <Select
                value={selectedCurrency}
                onChange={(e) => setSelectedCurrency(e.target.value)}
              >
                <MenuItem value="USD">USD</MenuItem>
                <MenuItem value="EUR">EUR</MenuItem>
                <MenuItem value="BRL">BRL</MenuItem>
                <MenuItem value="ARS">ARS</MenuItem>
              </Select>
            </FormControl>

            <ToggleButtonGroup
              value={selectedModel}
              exclusive
              onChange={(_, value) => {
                if (value) setSelectedModel(value);
              }}
              size="small"
            >
              <ToggleButton value="PROPHET">
                <Timeline />
              </ToggleButton>
              <ToggleButton value="LSTM">
                <ShowChart />
              </ToggleButton>
              <ToggleButton value="ENSEMBLE">
                <TrendingUp />
              </ToggleButton>
            </ToggleButtonGroup>

            <Tooltip title="Actualizar predicciones">
              <IconButton onClick={loadPredictions} size="small">
                <Refresh />
              </IconButton>
            </Tooltip>
          </Box>
        </Box>

        <Grid container spacing={2} sx={{ mb: 3 }}>
          <Grid item xs={12} md={8}>
            <Alert severity="info" icon={<Info />}>
              <Typography variant="body2">
                <strong>{getModelInfo()?.name}</strong>: {getModelInfo()?.description}
              </Typography>
            </Alert>
          </Grid>
          <Grid item xs={12} md={4}>
            <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
              {getModelInfo()?.accuracy && (
                <Tooltip title="Error porcentual medio del modelo en entrenamiento (menor = mejor)">
                  <Chip
                    label={getModelInfo()?.accuracy}
                    color="success"
                    size="small"
                  />
                </Tooltip>
              )}
              <Chip
                label="Próximas 24h"
                color="primary"
                size="small"
              />
            </Box>
          </Grid>
        </Grid>

        <Box sx={{ mb: 2 }}>
          <ToggleButtonGroup
            value={viewType}
            exclusive
            onChange={(_, value) => {
              if (value) setViewType(value);
            }}
            size="small"
            fullWidth
          >
            <ToggleButton value="rate">
              Tasa Oficial con Bandas de Confianza
            </ToggleButton>
            <ToggleButton value="buy_sell">
              Tasas de Compra y Venta
            </ToggleButton>
          </ToggleButtonGroup>
        </Box>

        <Box sx={{ height: 400 }}>
          {chartData.length === 0 ? (
            <Alert severity="info" sx={{ mt: 2 }}>
              Sin datos suficientes de predicción para {selectedCurrency}/BOB con el modelo {selectedModel}.
            </Alert>
          ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis
                tick={{ fontSize: 11 }}
                tickFormatter={(v) => formatNumber(v, 2)}
                domain={['auto', 'auto']}
                width={60}
              />
              <RTooltip formatter={tooltipFormatter} />
              <Legend />
              {viewType === 'rate' ? (
                <>
                  <Area
                    dataKey="band"
                    name="Banda de confianza"
                    stroke="none"
                    fill="rgba(75, 192, 192, 0.15)"
                    isAnimationActive={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="rate"
                    name="Predicción"
                    stroke="rgb(75, 192, 192)"
                    strokeWidth={2}
                    dot={{ r: 2 }}
                  />
                  {currentRate != null && (
                    <ReferenceLine
                      y={currentRate}
                      stroke="rgb(255, 99, 132)"
                      strokeDasharray="10 5"
                      label={{ value: 'Tasa Actual', position: 'insideTopRight', fontSize: 11 }}
                    />
                  )}
                </>
              ) : (
                <>
                  <Line
                    type="monotone"
                    dataKey="buy_rate"
                    name="Compra"
                    stroke="rgb(54, 162, 235)"
                    strokeWidth={2}
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="sell_rate"
                    name="Venta"
                    stroke="rgb(255, 99, 132)"
                    strokeWidth={2}
                    dot={false}
                  />
                </>
              )}
            </ComposedChart>
          </ResponsiveContainer>
          )}
        </Box>

        <Box sx={{ mt: 3 }}>
          <Typography variant="caption" color="text.secondary">
            * Las predicciones se actualizan cada hora y están basadas en análisis de datos históricos,
            tendencias del mercado y factores externos. Use estas predicciones como referencia, no como
            consejo financiero definitivo.
          </Typography>
        </Box>
      </CardContent>
    </Card>
  );
};

export default PredictionsChart;
