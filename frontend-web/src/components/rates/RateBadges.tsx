import React from 'react';
import { Box, Chip, Tooltip, Typography, Link } from '@mui/material';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import {
  SOURCE_CONFIG, LIVE_SOURCE_CONFIG,
  confidenceColor, confidenceDot, confidenceLabel,
} from './rateConfig';

// Badge for the live FX engine sources (binance / dolarblue / …).
export const LiveSourceBadge: React.FC<{ source: string; confidence: number }> = ({ source }) => {
  const cfg = LIVE_SOURCE_CONFIG[source] ?? LIVE_SOURCE_CONFIG['db_cache'];
  return (
    <Tooltip title={cfg.description} arrow>
      <Chip
        label={`${cfg.dot} ${cfg.label}`}
        size="small" color={cfg.color} variant="filled"
        sx={{ bgcolor: cfg.bgcolor, fontWeight: 700, fontSize: '0.65rem', height: 22, cursor: 'help' }}
      />
    </Tooltip>
  );
};

// Badge for the source_method of a stored ExchangeRate (API / SCRAP / MANUAL / INFERENCE).
export const SourceBadge: React.FC<{
  method: string; sourceUrl?: string | null;
  confidence?: number; fetchedAt?: string | null;
}> = ({ method, sourceUrl, confidence, fetchedAt }) => {
  const cfg = SOURCE_CONFIG[method] ?? SOURCE_CONFIG['MANUAL'];
  const tooltipContent = (
    <Box sx={{ p: 0.5, maxWidth: 280 }}>
      <Typography variant="caption" fontWeight="bold" display="block">{cfg.label}</Typography>
      <Typography variant="caption" display="block" sx={{ mb: 0.5 }}>{cfg.description}</Typography>
      {confidence !== undefined && (
        <Typography variant="caption" display="block">
          Confianza: <strong style={{ color: confidenceColor(confidence) }}>
            {confidenceDot(confidence)} {(confidence * 100).toFixed(0)}% — {confidenceLabel(confidence)}
          </strong>
        </Typography>
      )}
      {fetchedAt && (
        <Typography variant="caption" display="block">
          Consultado: {format(new Date(fetchedAt), 'dd/MM/yyyy HH:mm:ss', { locale: es })}
        </Typography>
      )}
      {sourceUrl && (
        <Typography variant="caption" display="block" sx={{ mt: 0.5, wordBreak: 'break-all' }}>
          URL: <Link href={sourceUrl} target="_blank" rel="noopener" color="inherit">{sourceUrl}</Link>
        </Typography>
      )}
    </Box>
  );
  return (
    <Tooltip title={tooltipContent} arrow placement="top">
      <Chip
        icon={cfg.icon as any} label={cfg.label} size="small" color={cfg.color} variant="filled"
        sx={{ bgcolor: cfg.bgcolor, cursor: 'help', fontWeight: 600, fontSize: '0.65rem', height: 22 }}
      />
    </Tooltip>
  );
};

// Compact confidence meter (dot + bar + %).
export const ConfidenceBar: React.FC<{ value: number }> = ({ value }) => {
  const pct   = Math.round(value * 100);
  const color = confidenceColor(value);
  return (
    <Tooltip title={`Confianza: ${pct}% — ${confidenceLabel(value)}`} arrow>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, cursor: 'help' }}>
        <Typography variant="caption" sx={{ color, fontWeight: 700, fontSize: '0.7rem', minWidth: 16 }}>
          {confidenceDot(value)}
        </Typography>
        <Box sx={{ width: 44, height: 4, bgcolor: '#e0e0e0', borderRadius: 2, overflow: 'hidden' }}>
          <Box sx={{ width: `${pct}%`, height: '100%', bgcolor: color, borderRadius: 2 }} />
        </Box>
        <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.65rem', minWidth: 28 }}>
          {pct}%
        </Typography>
      </Box>
    </Tooltip>
  );
};
