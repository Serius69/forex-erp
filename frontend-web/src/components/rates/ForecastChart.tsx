// src/components/rates/ForecastChart.tsx
import React, { useEffect, useState } from 'react';
import {
  Box, Card, CardContent, Typography, Select, MenuItem,
  FormControl, InputLabel, CircularProgress, Alert, Chip, ToggleButtonGroup, ToggleButton,
} from '@mui/material';
import {
  ComposedChart, Line, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import axios from 'axios';
import { format, parseISO } from 'date-fns';
import { es } from 'date-fns/locale';

interface ForecastPoint {
  date: string;
  buy: number;
  sell: number;
  lower?: number;
  upper?: number;
  confidence?: number;
}

interface HistoricalPoint {
  date: string;
  buy: number;
  sell: number;
}

interface ForecastData {
  currency: string;
  days: number;
  historical: HistoricalPoint[];
  forecast: ForecastPoint[];
  has_forecast: boolean;
}

const CURRENCIES = ['USD', 'EUR', 'BRL', 'ARS', 'PEN', 'CLP'];
const DAYS_OPTIONS = [7, 14, 21, 30];

const formatDate = (dateStr: string) => {
  try {
    return format(parseISO(dateStr), 'd MMM', { locale: es });
  } catch {
    return dateStr.substring(5, 10);
  }
};

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <Box sx={{ background: 'white', border: '1px solid #e0e0e0', p: 1.5, borderRadius: 1, fontSize: 12 }}>
      <Typography variant="caption" fontWeight={700} display="block" mb={0.5}>{label}</Typography>
      {payload.map((p: any) => (
        <Box key={p.dataKey} display="flex" justifyContent="space-between" gap={2}>
          <Typography variant="caption" color={p.color}>{p.name}:</Typography>
          <Typography variant="caption" fontWeight={600}>Bs {Number(p.value).toFixed(4)}</Typography>
        </Box>
      ))}
    </Box>
  );
};

const ForecastChart: React.FC = () => {
  const [data, setData] = useState<ForecastData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currency, setCurrency] = useState('USD');
  const [days, setDays] = useState(14);
  const [showType, setShowType] = useState<'sell' | 'buy' | 'both'>('sell');

  useEffect(() => {
    const fetch = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await axios.get(`/api/rates/forecast/?currency=${currency}&days=${days}`);
        setData(res.data);
      } catch (e: any) {
        setError('No hay datos de predicción disponibles aún. Entrena el modelo primero.');
      } finally {
        setLoading(false);
      }
    };
    fetch();
  }, [currency, days]);

  // Combinar histórico + forecast en una sola serie para el gráfico
  const chartData = React.useMemo(() => {
    if (!data) return [];
    const today = new Date().toISOString().split('T')[0];

    const historical = (data.historical || []).map(p => ({
      date:    formatDate(p.date),
      rawDate: p.date,
      buy_hist:  p.buy,
      sell_hist: p.sell,
      isHistorical: true,
    }));

    const forecast = (data.forecast || []).map(p => ({
      date:       formatDate(p.date),
      rawDate:    p.date,
      buy_pred:   p.buy,
      sell_pred:  p.sell,
      band_lower: p.lower,
      band_upper: p.upper,
      confidence: p.confidence,
      isHistorical: false,
    }));

    // Deduplicate by date keeping latest
    const merged = [...historical, ...forecast];
    const seen = new Set<string>();
    return merged.filter(p => {
      if (seen.has(p.rawDate)) return false;
      seen.add(p.rawDate);
      return true;
    });
  }, [data]);

  return (
    <Card>
      <CardContent>
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={2} flexWrap="wrap" gap={1}>
          <Box>
            <Typography variant="h6" fontWeight={600}>Predicción de Tipo de Cambio</Typography>
            <Typography variant="caption" color="text.secondary">
              Histórico real + forecast Prophet/LSTM
            </Typography>
          </Box>
          <Box display="flex" gap={1} flexWrap="wrap" alignItems="center">
            <FormControl size="small" sx={{ minWidth: 100 }}>
              <InputLabel>Divisa</InputLabel>
              <Select value={currency} label="Divisa" onChange={e => setCurrency(e.target.value)}>
                {CURRENCIES.map(c => <MenuItem key={c} value={c}>{c}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 100 }}>
              <InputLabel>Horizonte</InputLabel>
              <Select value={days} label="Horizonte" onChange={e => setDays(Number(e.target.value))}>
                {DAYS_OPTIONS.map(d => <MenuItem key={d} value={d}>{d} días</MenuItem>)}
              </Select>
            </FormControl>
            <ToggleButtonGroup size="small" value={showType} exclusive onChange={(_, v) => v && setShowType(v)}>
              <ToggleButton value="sell">Venta</ToggleButton>
              <ToggleButton value="buy">Compra</ToggleButton>
              <ToggleButton value="both">Ambos</ToggleButton>
            </ToggleButtonGroup>
          </Box>
        </Box>

        {loading && <Box display="flex" justifyContent="center" py={4}><CircularProgress /></Box>}

        {error && !loading && (
          <Alert severity="info" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {!loading && data && !error && (
          <>
            {!data.has_forecast && (
              <Alert severity="warning" sx={{ mb: 2 }}>
                No hay predicciones entrenadas. Ve a Predicciones para entrenar el modelo.
              </Alert>
            )}
            <ResponsiveContainer width="100%" height={320}>
              <ComposedChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} interval={Math.floor(chartData.length / 8)} />
                <YAxis
                  tickFormatter={v => `Bs ${v.toFixed(2)}`}
                  tick={{ fontSize: 11 }}
                  domain={['auto', 'auto']}
                />
                <Tooltip content={<CustomTooltip />} />
                <Legend />

                {/* Banda de confianza forecast */}
                {data.has_forecast && (
                  <Area
                    dataKey="band_upper" fill="#2196f3" stroke="none" opacity={0.1}
                    name="Banda superior" legendType="none"
                  />
                )}
                {data.has_forecast && (
                  <Area
                    dataKey="band_lower" fill="white" stroke="none" opacity={1}
                    name="Banda inferior" legendType="none"
                  />
                )}

                {/* Línea de hoy */}
                <ReferenceLine x={formatDate(new Date().toISOString())} stroke="#757575"
                  strokeDasharray="4 4" label={{ value: 'Hoy', fill: '#757575', fontSize: 11 }} />

                {/* Histórico venta */}
                {(showType === 'sell' || showType === 'both') && (
                  <Line dataKey="sell_hist" name="Venta (real)" stroke="#1976d2"
                    strokeWidth={2} dot={false} connectNulls />
                )}
                {/* Histórico compra */}
                {(showType === 'buy' || showType === 'both') && (
                  <Line dataKey="buy_hist" name="Compra (real)" stroke="#388e3c"
                    strokeWidth={2} dot={false} connectNulls />
                )}
                {/* Forecast venta */}
                {data.has_forecast && (showType === 'sell' || showType === 'both') && (
                  <Line dataKey="sell_pred" name="Venta (pred.)" stroke="#1976d2"
                    strokeWidth={2} strokeDasharray="5 5" dot={false} connectNulls />
                )}
                {/* Forecast compra */}
                {data.has_forecast && (showType === 'buy' || showType === 'both') && (
                  <Line dataKey="buy_pred" name="Compra (pred.)" stroke="#388e3c"
                    strokeWidth={2} strokeDasharray="5 5" dot={false} connectNulls />
                )}
              </ComposedChart>
            </ResponsiveContainer>

            {data.has_forecast && data.forecast.length > 0 && (
              <Box mt={1} display="flex" gap={1} flexWrap="wrap">
                <Chip size="small" label="——— Real" sx={{ borderColor: '#1976d2', color: '#1976d2' }} variant="outlined" />
                <Chip size="small" label="- - - Predicción" sx={{ borderColor: '#ff9800', color: '#ff9800' }} variant="outlined" />
                <Chip size="small" label={`Confianza: ${((data.forecast[0]?.confidence ?? 0) * 100).toFixed(0)}%`}
                  color="info" />
              </Box>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
};

export default ForecastChart;
