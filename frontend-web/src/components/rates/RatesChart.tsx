/**
 * RatesChart — gráfico de serie histórica de datos crudos por fuente.
 *
 * Consume GET /api/rates/raw-history/?par=USD/BOB&desde=…&hasta=…&fuente=…
 * Permite seleccionar par, período y ver líneas por fuente.
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, CircularProgress, FormControl, InputLabel, MenuItem,
  Paper, Select, ToggleButton, ToggleButtonGroup, Typography, Alert,
} from '@mui/material';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { format, parseISO, subDays, subMonths } from 'date-fns';
import { es } from 'date-fns/locale';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';

// ── Config ────────────────────────────────────────────────────────────────────

const PARES = ['USD/BOB', 'BRL/BOB', 'EUR/BOB', 'ARS/BOB', 'PEN/BOB', 'CLP/BOB'];

const PERIODOS: { label: string; days: number }[] = [
  { label: '24h',  days: 1  },
  { label: '7d',   days: 7  },
  { label: '30d',  days: 30 },
  { label: '90d',  days: 90 },
];

const LINE_COLORS: string[] = [
  '#1976d2', '#d32f2f', '#2e7d32', '#f57c00', '#7b1fa2',
  '#0288d1', '#558b2f', '#c62828', '#4527a0', '#00838f',
];

// ── Tipos ─────────────────────────────────────────────────────────────────────

interface RawPoint {
  ts:     string;
  fuente: string;
  compra: number | null;
  venta:  number | null;
  mid:    number | null;
  valido: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function buildChartData(points: RawPoint[]): {
  data:    Record<string, any>[];
  fuentes: string[];
} {
  const fuentes = Array.from(new Set(points.map(p => p.fuente)));
  const byTs    = new Map<string, Record<string, any>>();

  for (const p of points) {
    const label = format(parseISO(p.ts), 'dd/MM HH:mm', { locale: es });
    if (!byTs.has(label)) {
      byTs.set(label, { ts: label });
    }
    const row = byTs.get(label)!;
    row[p.fuente] = p.mid ?? p.compra ?? null;
  }

  return {
    data:    Array.from(byTs.values()),
    fuentes,
  };
}

// ── Component ─────────────────────────────────────────────────────────────────

const RatesChart: React.FC = () => {
  const [par,     setPar]     = useState('USD/BOB');
  const [dias,    setDias]    = useState(7);
  const [points,  setPoints]  = useState<RawPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState(false);

  const { enqueueSnackbar } = useSnackbar();

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const hasta = new Date();
      const desde = subDays(hasta, dias);
      const res = await api.get('/rates/raw-history/', {
        params: {
          par,
          desde: desde.toISOString(),
          hasta: hasta.toISOString(),
          limit: 2000,
        },
      });
      setPoints((res.data.puntos ?? []).filter((p: RawPoint) => p.valido));
    } catch {
      setError(true);
      enqueueSnackbar('Error al cargar el historial', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [par, dias, enqueueSnackbar]);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  const { data: chartData, fuentes } = buildChartData(points);

  return (
    <Box>
      {/* Controles */}
      <Box display="flex" gap={2} alignItems="center" mb={2} flexWrap="wrap">
        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel>Par</InputLabel>
          <Select value={par} label="Par" onChange={e => setPar(e.target.value)}>
            {PARES.map(p => <MenuItem key={p} value={p}>{p}</MenuItem>)}
          </Select>
        </FormControl>

        <ToggleButtonGroup
          value={dias}
          exclusive
          onChange={(_, v) => v != null && setDias(v)}
          size="small"
        >
          {PERIODOS.map(p => (
            <ToggleButton key={p.days} value={p.days} sx={{ px: 1.5, fontWeight: 700 }}>
              {p.label}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>

        {fuentes.length > 0 && (
          <Typography variant="caption" color="text.secondary">
            {fuentes.length} fuentes · {points.length} puntos
          </Typography>
        )}
      </Box>

      {/* Gráfica */}
      <Paper variant="outlined" sx={{ p: 2 }}>
        {loading ? (
          <Box display="flex" justifyContent="center" alignItems="center" height={340}>
            <CircularProgress />
          </Box>
        ) : error ? (
          <Alert severity="error">Error al cargar el historial de tasas.</Alert>
        ) : chartData.length === 0 ? (
          <Box display="flex" justifyContent="center" alignItems="center" height={340}>
            <Typography color="text.disabled">Sin datos para el período seleccionado</Typography>
          </Box>
        ) : (
          <ResponsiveContainer width="100%" height={340}>
            <LineChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="ts"
                tick={{ fontSize: 10 }}
                interval="preserveStartEnd"
                tickLine={false}
              />
              <YAxis
                domain={['auto', 'auto']}
                tick={{ fontSize: 11 }}
                tickFormatter={v => v.toFixed(2)}
                width={56}
              />
              <RTooltip
                formatter={(v: any, name: string) => [
                  v != null ? Number(v).toFixed(4) : '—',
                  name,
                ]}
                contentStyle={{ fontSize: 12 }}
              />
              <Legend
                wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
                formatter={(value) => value.replace(/_/g, ' ')}
              />
              {fuentes.map((fuente, i) => (
                <Line
                  key={fuente}
                  type="monotone"
                  dataKey={fuente}
                  stroke={LINE_COLORS[i % LINE_COLORS.length]}
                  dot={false}
                  strokeWidth={1.5}
                  connectNulls
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </Paper>
    </Box>
  );
};

export default RatesChart;
