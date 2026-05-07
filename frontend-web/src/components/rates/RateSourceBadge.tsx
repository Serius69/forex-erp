// src/components/rates/RateSourceBadge.tsx
import React from 'react';
import { Chip, Tooltip, Typography, Box, Link } from '@mui/material';
import { CheckCircle, Warning, Error as ErrorIcon } from '@mui/icons-material';

// ── Config de fuentes conocidas ───────────────────────────────────────────────

interface SourceConfig {
  label:       string;
  color:       'success' | 'warning' | 'error' | 'info' | 'default';
  bg:          string;
  textColor:   string;
  description: string;
  icon?:       React.ReactNode;
}

const SOURCE_CONFIG: Record<string, SourceConfig> = {
  binance:   { label: 'Binance',    color: 'success', bg: '#e8f5e9', textColor: '#1b5e20', description: 'Binance P2P — USDT/BOB en tiempo real',          icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  bybit:     { label: 'Bybit',      color: 'success', bg: '#e0f7fa', textColor: '#006064', description: 'Bybit P2P — USDT/BOB en tiempo real',             icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  bitget:    { label: 'Bitget',     color: 'success', bg: '#e8f5e9', textColor: '#2e7d32', description: 'Bitget P2P — USDT/BOB en tiempo real',            icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  airtm:     { label: 'Airtm',      color: 'info',    bg: '#e3f2fd', textColor: '#0d47a1', description: 'Airtm — plataforma P2P de remesas',               icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  eldorado:  { label: 'Eldorado',   color: 'info',    bg: '#f3e5f5', textColor: '#4a148c', description: 'Eldorado.io — P2P criptomonedas',                 icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  wallbit:   { label: 'Wallbit',    color: 'info',    bg: '#e8eaf6', textColor: '#1a237e', description: 'Wallbit — exchange cripto Bolivia',               icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  saldoar:   { label: 'Saldoar',    color: 'warning', bg: '#fff3e0', textColor: '#e65100', description: 'Saldoar — plataforma AR/BOB',                     icon: <Warning sx={{ fontSize: 12 }} /> },
  dolarblue: { label: 'DolarBlue',  color: 'warning', bg: '#fff8e1', textColor: '#f57f17', description: 'DolarBlueBolivia — referencia paralela (scraping)',icon: <Warning sx={{ fontSize: 12 }} /> },
  db_cache:  { label: 'Caché',      color: 'default', bg: '#f5f5f5', textColor: '#616161', description: 'Dato en caché — sin actualización en tiempo real', icon: undefined },
  // Exchange rate reference APIs
  open_er_api:   { label: 'Open ER API',  color: 'info',    bg: '#e3f2fd', textColor: '#0d47a1', description: 'open.er-api.com — tasa de referencia mid-market',       icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  external_api:  { label: 'API externa',  color: 'info',    bg: '#e3f2fd', textColor: '#0d47a1', description: 'API externa de referencia (mid-market)',                icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  db_historical: { label: 'Histórico DB', color: 'default', bg: '#fafafa', textColor: '#616161', description: 'Tasa histórica de la base de datos — puede estar desactualizada', icon: undefined },
  okx:           { label: 'OKX',          color: 'success', bg: '#e8f5e9', textColor: '#2e7d32', description: 'OKX P2P — tasa en tiempo real',                         icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  // Nuevas fuentes bolivianas y Latam
  DOLARESABOLIVIANOS_LLM:  { label: 'DólaresABolivianos', color: 'success', bg: '#e8f5e9', textColor: '#1b5e20', description: 'dolaresabolivianos.com — agregador USDT/BOB Bolivia', icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  DOLARESABOLIVIANOS_LAST: { label: 'DólaresABo (último)', color: 'success', bg: '#e8f5e9', textColor: '#2e7d32', description: 'dolaresabolivianos.com — último registro puntual USDT/BOB', icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  CRIPTOYA_BOB:  { label: 'CriptoYa BOB',  color: 'success', bg: '#e8f5e9', textColor: '#1b5e20', description: 'CriptoYa — USDT/BOB agregado Latam',   icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  CRIPTOYA_ARS:  { label: 'CriptoYa ARS',  color: 'info',    bg: '#e3f2fd', textColor: '#0d47a1', description: 'CriptoYa — ARS/BOB vía USDT',           icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  CRIPTOYA_CLP:  { label: 'CriptoYa CLP',  color: 'info',    bg: '#e3f2fd', textColor: '#0d47a1', description: 'CriptoYa — CLP/BOB vía USDT',           icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  CRIPTOYA_PEN:  { label: 'CriptoYa PEN',  color: 'info',    bg: '#e3f2fd', textColor: '#0d47a1', description: 'CriptoYa — PEN/BOB vía USDT',           icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  CRIPTOYA_BRL:  { label: 'CriptoYa BRL',  color: 'info',    bg: '#e3f2fd', textColor: '#0d47a1', description: 'CriptoYa — BRL/BOB vía USDT',           icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  DOLARAPI_OFICIAL:  { label: 'DolarApi Oficial',  color: 'default', bg: '#f5f5f5', textColor: '#616161', description: 'bo.dolarapi.com — tipo de cambio oficial BCB', icon: undefined },
  DOLARAPI_TARJETA:  { label: 'DolarApi Tarjeta',  color: 'default', bg: '#f5f5f5', textColor: '#616161', description: 'bo.dolarapi.com — tipo de cambio tarjeta',     icon: undefined },
  DOLARAPI_BLUE:     { label: 'DolarApi Blue',     color: 'warning', bg: '#fff8e1', textColor: '#f57f17', description: 'bo.dolarapi.com — tipo de cambio blue/paralelo', icon: <Warning sx={{ fontSize: 12 }} /> },
  DOLARAPI_PARALELO: { label: 'DolarApi Paralelo', color: 'warning', bg: '#fff8e1', textColor: '#f57f17', description: 'bo.dolarapi.com — tipo de cambio paralelo',     icon: <Warning sx={{ fontSize: 12 }} /> },
  // Source methods
  API:       { label: 'API',        color: 'success', bg: '#e8f5e9', textColor: '#1b5e20', description: 'Dato en tiempo real desde API verificada',        icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  SCRAP:     { label: 'Scraping',   color: 'warning', bg: '#fff8e1', textColor: '#f57f17', description: 'Dato obtenido por web scraping',                  icon: <Warning sx={{ fontSize: 12 }} /> },
  MANUAL:    { label: 'Manual',     color: 'info',    bg: '#e3f2fd', textColor: '#0d47a1', description: 'Tasa ingresada manualmente por operador',         icon: <CheckCircle sx={{ fontSize: 12 }} /> },
  INFERENCE: { label: 'Inferida',   color: 'error',   bg: '#ffebee', textColor: '#b71c1c', description: 'Tasa estimada — sin fuente en tiempo real. NO usar en transacciones.', icon: <ErrorIcon sx={{ fontSize: 12 }} /> },
};

const FALLBACK: SourceConfig = {
  label: 'Desconocido', color: 'default', bg: '#f5f5f5', textColor: '#757575',
  description: 'Fuente no identificada',
};

// ── Componente ────────────────────────────────────────────────────────────────

interface RateSourceBadgeProps {
  /** Nombre del proveedor (binance, bybit…) o método (API, MANUAL, SCRAP, INFERENCE) */
  source:      string;
  /** Confianza 0-1, opcional */
  confidence?: number;
  /** Timestamp de cuando se obtuvo el dato */
  fetchedAt?:  string | null;
  /** URL de la fuente para auditoría */
  sourceUrl?:  string | null;
  size?:       'small' | 'medium';
}

const resolveSourceConfig = (source: string): SourceConfig => {
  if (SOURCE_CONFIG[source]) return SOURCE_CONFIG[source];
  // Handle prefixed sources: "db_historical:OPEN_ER_API", "historical:binance", etc.
  const prefix = source.split(':')[0];
  if (SOURCE_CONFIG[prefix]) return SOURCE_CONFIG[prefix];
  return FALLBACK;
};

const RateSourceBadge: React.FC<RateSourceBadgeProps> = ({
  source, confidence, fetchedAt, sourceUrl, size = 'small',
}) => {
  const cfg = resolveSourceConfig(source);

  const tooltipContent = (
    <Box sx={{ p: 0.5, maxWidth: 280 }}>
      <Typography variant="caption" fontWeight={700} display="block">{cfg.label}</Typography>
      <Typography variant="caption" display="block" sx={{ mb: 0.5 }}>{cfg.description}</Typography>
      {confidence !== undefined && (
        <Typography variant="caption" display="block">
          Confianza:{' '}
          <strong style={{ color: confidence >= 0.9 ? '#4caf50' : confidence >= 0.7 ? '#ff9800' : '#f44336' }}>
            {(confidence * 100).toFixed(0)}%
          </strong>
        </Typography>
      )}
      {fetchedAt && (
        <Typography variant="caption" display="block">
          Actualizado: {new Date(fetchedAt).toLocaleString('es-BO', { timeZone: 'America/La_Paz' })}
        </Typography>
      )}
      {sourceUrl && (
        <Box mt={0.5}>
          <Link href={sourceUrl} target="_blank" rel="noopener" sx={{ fontSize: '0.65rem', color: 'inherit', wordBreak: 'break-all' }}>
            {sourceUrl}
          </Link>
        </Box>
      )}
    </Box>
  );

  return (
    <Tooltip title={tooltipContent} arrow placement="top">
      <Chip
        icon={cfg.icon as any}
        label={cfg.label}
        size={size}
        color={cfg.color}
        variant="filled"
        sx={{
          bgcolor:    cfg.bg,
          color:      cfg.textColor,
          fontWeight: 700,
          fontSize:   size === 'small' ? '0.62rem' : '0.72rem',
          height:     size === 'small' ? 22 : 28,
          cursor:     'help',
          '& .MuiChip-icon': { color: cfg.textColor, marginLeft: '6px' },
        }}
      />
    </Tooltip>
  );
};

export default RateSourceBadge;
