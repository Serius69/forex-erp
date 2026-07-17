import React from 'react';
import { CheckCircle, Warning, Error as ErrorIcon } from '@mui/icons-material';

// ── Source method config ──────────────────────────────────────────────────────
export const SOURCE_CONFIG: Record<string, {
  color: 'success' | 'warning' | 'error' | 'default';
  bgcolor: string;
  icon: React.ReactNode;
  label: string;
  description: string;
}> = {
  API: {
    color: 'success', bgcolor: '#e8f5e9',
    icon: <CheckCircle sx={{ fontSize: 14 }} />,
    label: 'API',
    description: 'Dato en tiempo real desde API externa verificada',
  },
  SCRAP: {
    color: 'warning', bgcolor: '#fff8e1',
    icon: <Warning sx={{ fontSize: 14 }} />,
    label: 'SCRAPING',
    description: 'Dato obtenido por web scraping del sitio oficial',
  },
  MANUAL: {
    color: 'default', bgcolor: '#e3f2fd',
    icon: <CheckCircle sx={{ fontSize: 14 }} />,
    label: 'MANUAL',
    description: 'Tasa ingresada manualmente por un administrador',
  },
  INFERENCE: {
    color: 'error', bgcolor: '#ffebee',
    icon: <ErrorIcon sx={{ fontSize: 14 }} />,
    label: 'INFERIDA',
    description: 'Tasa estimada — sin fuente en tiempo real. NO usar en transacciones.',
  },
};

export const LIVE_SOURCE_CONFIG: Record<string, {
  color: 'success' | 'warning' | 'info' | 'default';
  bgcolor: string; dot: string; label: string; description: string;
}> = {
  binance:  { color: 'success', bgcolor: '#e8f5e9', dot: '🟢', label: 'BINANCE',     description: 'Binance P2P en tiempo real (USDT/BOB)' },
  dolarblue:{ color: 'warning', bgcolor: '#fff8e1', dot: '🟡', label: 'DOLARBLUE',   description: 'Referencia paralela — DolarBlueBolivia (scraping)' },
  db_cache: { color: 'warning', bgcolor: '#fff8e1', dot: '🟡', label: 'SCRAPING',    description: 'Dato en caché de fuente scrapeada' },
  MANUAL:   { color: 'info',    bgcolor: '#e3f2fd', dot: '🔵', label: 'MANUAL',      description: 'Tasa ingresada manualmente' },
};

// ── Confidence helpers ────────────────────────────────────────────────────────
export const confidenceColor = (v: number) =>
  v >= 0.90 ? '#4caf50' : v >= 0.70 ? '#ff9800' : '#f44336';

export const confidenceDot = (v: number) =>
  v >= 0.90 ? '🟢' : v >= 0.70 ? '🟡' : '🔴';

export const confidenceLabel = (v: number) =>
  v >= 0.90 ? 'Alta' : v >= 0.70 ? 'Media' : 'Baja';

export const isStale = (timestamp: string | null | undefined, thresholdMinutes = 30): boolean => {
  if (!timestamp) return true;
  return (Date.now() - new Date(timestamp).getTime()) > thresholdMinutes * 60 * 1000;
};
