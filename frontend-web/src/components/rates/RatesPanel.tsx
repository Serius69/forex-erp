/**
 * RatesPanel — tabla de consenso de tasas en tiempo real.
 *
 * Conecta al WebSocket /ws/rates-live/ via useRatesWebSocket.
 * Muestra Par | Compra | Venta | Consenso | Fuentes | Confianza | Variación | Actualizado.
 * Reconexión automática con backoff exponencial.
 */
import React, { useMemo } from 'react';
import {
  Box, Chip, Paper, Skeleton, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Tooltip, Typography,
} from '@mui/material';
import {
  TrendingUp, TrendingDown, TrendingFlat,
  WifiOff, Wifi,
} from '@mui/icons-material';
import { alpha } from '@mui/material/styles';
import { formatDistanceToNow, parseISO } from 'date-fns';
import { es } from 'date-fns/locale';
import { useRatesWebSocket, ConsensusPar } from '../../hooks/useRatesWebSocket';

// ── Helpers de presentación ──────────────────────────────────────────────────

const TENDENCIA_CONFIG = {
  ALCISTA: { color: 'success' as const, icon: <TrendingUp fontSize="small" />,  label: 'Alza' },
  BAJISTA: { color: 'error'   as const, icon: <TrendingDown fontSize="small" />, label: 'Baja' },
  NEUTRAL: { color: 'default' as const, icon: <TrendingFlat fontSize="small" />, label: 'Estable' },
};

function confidenceBg(pct: number): string {
  if (pct >= 85) return '#e8f5e9';
  if (pct >= 65) return '#fff8e1';
  return '#ffebee';
}

function confidenceColor(pct: number): string {
  if (pct >= 85) return '#2e7d32';
  if (pct >= 65) return '#f57f17';
  return '#b71c1c';
}

function formatRate(n: number | null | undefined): string {
  if (n == null) return '—';
  return n.toFixed(4);
}

function timeSince(ts: string | null): string {
  if (!ts) return '—';
  try {
    return formatDistanceToNow(parseISO(ts), { locale: es, addSuffix: true });
  } catch {
    return '—';
  }
}

// ── Skeleton row ─────────────────────────────────────────────────────────────

const SkeletonRow: React.FC = () => (
  <TableRow>
    {[120, 80, 80, 80, 60, 70, 90, 100].map((w, i) => (
      <TableCell key={i}><Skeleton variant="text" width={w} /></TableCell>
    ))}
  </TableRow>
);

// ── RatesPanel ────────────────────────────────────────────────────────────────

interface RatesPanelProps {
  /** Pares a mostrar. Si se omite, muestra todos los recibidos. */
  pares?: string[];
}

const RatesPanel: React.FC<RatesPanelProps> = ({ pares }) => {
  const { rates, connected, lastUpdate } = useRatesWebSocket();

  const rows = useMemo(() => {
    const all = Object.entries(rates) as [string, ConsensusPar][];
    if (!pares || pares.length === 0) return all;
    return all.filter(([par]) => pares.includes(par));
  }, [rates, pares]);

  const isLoading = rows.length === 0 && !lastUpdate;

  return (
    <Box>
      {/* Header de estado */}
      <Box display="flex" alignItems="center" gap={1} mb={1.5}>
        <Chip
          size="small"
          icon={connected ? <Wifi fontSize="small" /> : <WifiOff fontSize="small" />}
          label={connected ? 'En vivo' : 'Reconectando…'}
          color={connected ? 'success' : 'warning'}
          sx={{ fontWeight: 700, fontSize: '0.65rem', height: 22 }}
        />
        {lastUpdate && (
          <Typography variant="caption" color="text.secondary">
            Actualizado {timeSince(lastUpdate)}
          </Typography>
        )}
        {rows.length > 0 && (
          <Typography variant="caption" color="text.disabled">
            · {rows.length} par{rows.length !== 1 ? 'es' : ''} · {rows.reduce((s, [, v]) => s + v.fuentes, 0)} fuentes
          </Typography>
        )}
      </Box>

      <TableContainer component={Paper} variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow sx={{ bgcolor: alpha('#1565c0', 0.04) }}>
              <TableCell sx={{ fontWeight: 700 }}>Par</TableCell>
              <TableCell align="right" sx={{ fontWeight: 700 }}>Compra</TableCell>
              <TableCell align="right" sx={{ fontWeight: 700 }}>Venta</TableCell>
              <TableCell align="right" sx={{ fontWeight: 700 }}>Consenso</TableCell>
              <TableCell align="center" sx={{ fontWeight: 700 }}>Fuentes</TableCell>
              <TableCell align="center" sx={{ fontWeight: 700 }}>Confianza</TableCell>
              <TableCell align="center" sx={{ fontWeight: 700 }}>Variación 24h</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Actualizado</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {isLoading
              ? Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} />)
              : rows.map(([par, data]) => {
                  const tc        = TENDENCIA_CONFIG[data.tendencia] ?? TENDENCIA_CONFIG.NEUTRAL;
                  const cambio    = data.cambio_pct ?? 0;
                  const cambioStr = `${cambio >= 0 ? '+' : ''}${cambio.toFixed(2)}%`;

                  return (
                    <TableRow key={par} hover>
                      <TableCell>
                        <Typography fontWeight={800} sx={{ fontFamily: 'monospace', fontSize: '0.9rem' }}>
                          {par}
                        </Typography>
                      </TableCell>

                      <TableCell align="right">
                        <Typography
                          color="success.main"
                          fontWeight={700}
                          sx={{ fontVariantNumeric: 'tabular-nums' }}
                        >
                          {formatRate(data.compra)}
                        </Typography>
                      </TableCell>

                      <TableCell align="right">
                        <Typography
                          color="error.main"
                          fontWeight={700}
                          sx={{ fontVariantNumeric: 'tabular-nums' }}
                        >
                          {formatRate(data.venta)}
                        </Typography>
                      </TableCell>

                      <TableCell align="right">
                        <Typography
                          fontWeight={900}
                          sx={{ fontVariantNumeric: 'tabular-nums', fontSize: '0.95rem' }}
                        >
                          {formatRate(data.consenso)}
                        </Typography>
                      </TableCell>

                      <TableCell align="center">
                        <Chip
                          label={data.fuentes}
                          size="small"
                          color={data.fuentes >= 3 ? 'primary' : 'default'}
                          sx={{ fontWeight: 700, minWidth: 32, height: 20, fontSize: '0.7rem' }}
                        />
                      </TableCell>

                      <TableCell align="center">
                        <Tooltip title={`Confianza: ${data.confianza}%`} arrow>
                          <Box
                            sx={{
                              display: 'inline-flex', alignItems: 'center', gap: 0.5,
                              px: 1, py: 0.25, borderRadius: 1,
                              bgcolor: confidenceBg(data.confianza),
                              cursor: 'help',
                            }}
                          >
                            <Typography
                              variant="caption"
                              fontWeight={700}
                              sx={{ color: confidenceColor(data.confianza), fontSize: '0.75rem' }}
                            >
                              {data.confianza}%
                            </Typography>
                          </Box>
                        </Tooltip>
                      </TableCell>

                      <TableCell align="center">
                        <Chip
                          icon={tc.icon}
                          label={cambioStr}
                          size="small"
                          color={tc.color}
                          variant="outlined"
                          sx={{ fontWeight: 700, fontSize: '0.68rem', height: 22 }}
                        />
                      </TableCell>

                      <TableCell>
                        <Typography variant="caption" color="text.secondary">
                          {timeSince(lastUpdate)}
                        </Typography>
                      </TableCell>
                    </TableRow>
                  );
                })
            }
            {!isLoading && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} align="center" sx={{ py: 4 }}>
                  <Typography color="text.disabled" variant="body2">
                    Sin datos de consenso disponibles.{' '}
                    {connected ? 'Esperando primera actualización…' : 'Sin conexión al servidor.'}
                  </Typography>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
};

export default RatesPanel;
