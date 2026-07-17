import React from 'react';
import { Box, Typography, Grid } from '@mui/material';
import RateCard from './RateCard';
import RatesPanel from './RatesPanel';
import SourcesGrid from './SourcesGrid';

// ── Digital Rates Section (Tab "Tasas Digitales") ─────────────────────────────
const DIGITAL_CURRENCIES = ['USD', 'EUR', 'BRL', 'PEN', 'CLP', 'ARS'];

const DigitalRatesSection: React.FC = () => {
  return (
    <Box>
      {/* Motor FX — Cards en tiempo real */}
      <Box mb={4}>
        <Box display="flex" alignItems="center" gap={1.5} mb={2}>
          <Box>
            <Typography variant="overline" color="text.secondary" sx={{ fontSize: '0.65rem', letterSpacing: 1 }}>
              MOTOR FX — FUENTE EN TIEMPO REAL
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Tasas obtenidas directamente desde P2P crypto y scraping. Confianza, anomalías y trazabilidad completa.
            </Typography>
          </Box>
        </Box>
        <Grid container spacing={2}>
          {DIGITAL_CURRENCIES.map(cur => (
            <Grid item xs={12} sm={6} md={4} key={cur}>
              <RateCard currency={cur} refreshInterval={60_000} />
            </Grid>
          ))}
        </Grid>
      </Box>

      {/* Todas las fuentes por plataforma */}
      <Box mb={4}>
        <Box mb={1.5}>
          <Typography variant="overline" color="text.secondary" sx={{ fontSize: '0.65rem', letterSpacing: 1 }}>
            TODAS LAS PLATAFORMAS — TIEMPO REAL
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Tasas individuales por fuente: Binance, Bitget, Bybit, OKX, El Dorado, Wallbit, Airtm, SaldoAR y más.
            Actualización automática cada 90 segundos.
          </Typography>
        </Box>
        <SourcesGrid />
      </Box>

      {/* Consenso WebSocket — RatesPanel */}
      <Box>
        <Box mb={1.5}>
          <Typography variant="overline" color="text.secondary" sx={{ fontSize: '0.65rem', letterSpacing: 1 }}>
            CONSENSO MULTI-FUENTE (WEBSOCKET)
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Tasas de consenso calculadas en tiempo real ponderando múltiples fuentes.
            Variación 24h, tendencia y confianza global.
          </Typography>
        </Box>
        <RatesPanel />
      </Box>
    </Box>
  );
};

export default DigitalRatesSection;
