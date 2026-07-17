import React from 'react';
import { Box, Typography, Grid, Chip, Alert } from '@mui/material';
import { Psychology } from '@mui/icons-material';
import PredictionCard from './PredictionCard';

// ── Predictions Section (Tab "Predicciones ML") ───────────────────────────────
const PREDICTION_PAIRS = [
  { pair: 'USD-BOB', color: '#2563eb' },
  { pair: 'EUR-BOB', color: '#7c3aed' },
  { pair: 'BRL-BOB', color: '#059669' },
  { pair: 'PEN-BOB', color: '#d97706' },
  { pair: 'CLP-BOB', color: '#db2777' },
  { pair: 'ARS-BOB', color: '#dc2626' },
];

const PredictionsSection: React.FC = () => {
  const [horizon, setHorizon] = React.useState<'1h' | '4h' | '24h' | '7d'>('24h');

  return (
    <Box>
      {/* Header con selector de horizonte */}
      <Box display="flex" alignItems="center" justifyContent="space-between" mb={2} flexWrap="wrap" gap={1}>
        <Box>
          <Typography variant="overline" color="text.secondary" sx={{ fontSize: '0.65rem', letterSpacing: 1 }}>
            MOTOR ML — ENSEMBLE DE 5 MODELOS
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Prophet · BiLSTM · XGBoost · ARIMA · Ridge. Pesos dinámicos por PSI drift.
            Intervalo de confianza 95%.
          </Typography>
        </Box>
        <Box display="flex" gap={0.5}>
          {(['1h', '4h', '24h', '7d'] as const).map(h => (
            <Chip
              key={h}
              label={h}
              size="small"
              onClick={() => setHorizon(h)}
              color={horizon === h ? 'info' : 'default'}
              variant={horizon === h ? 'filled' : 'outlined'}
              sx={{ fontWeight: 700, fontSize: '0.7rem', cursor: 'pointer' }}
            />
          ))}
        </Box>
      </Box>

      <Alert severity="info" sx={{ mb: 2.5, py: 0.5 }} icon={<Psychology />}>
        Los pronósticos son estimaciones estadísticas basadas en datos históricos.
        <strong> No garantizan valores futuros.</strong> Úsalos como referencia operacional, no como base única de decisión.
      </Alert>

      <Grid container spacing={2}>
        {PREDICTION_PAIRS.map(({ pair, color }) => (
          <Grid item xs={12} sm={6} md={4} key={pair}>
            <PredictionCard pair={pair} horizon={horizon} color={color} />
          </Grid>
        ))}
      </Grid>
    </Box>
  );
};

export default PredictionsSection;
