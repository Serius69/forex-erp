/**
 * DecisionesPage — Módulo 3: Motor de Decisiones
 *
 * Panel "¿Comprar o Vender?" con:
 * - TC actual y comparación de fuentes
 * - TC histórico (gráfico sparkline)
 * - TC mercado paralelo
 * - Recomendación: COMPRAR / VENDER / ESPERAR
 * - Precio sugerido y margen esperado
 * - Nivel de riesgo
 * - Botón directo para abrir TransactionForm pre-llenado
 */
import React, { useState } from 'react';
import {
  Box, Typography, Grid, Card, CardContent,
  Divider, Chip, Alert, IconButton, Tooltip,
  Button, Select, MenuItem, FormControl, InputLabel,
} from '@mui/material';
import {
  Psychology, Refresh, TrendingUp, TrendingDown, Remove,
  SwapHoriz, Lightbulb,
} from '@mui/icons-material';
import { alpha } from '@mui/material/styles';
import { TOKENS } from '../../styles/theme';
import DecisionCard, { type TransactionPreset } from '../dashboard/DecisionCard';
import TransactionForm from '../transactions/TransactionForm';

const CURRENCIES = ['USD', 'EUR', 'CLP', 'PEN', 'BRL', 'ARS'];

const FLAGS: Record<string, string> = {
  USD: '🇺🇸', EUR: '🇪🇺', CLP: '🇨🇱', PEN: '🇵🇪', BRL: '🇧🇷', ARS: '🇦🇷',
};

const DecisionesPage: React.FC = () => {
  const [formOpen,    setFormOpen]    = useState(false);
  const [preset,      setPreset]      = useState<TransactionPreset | undefined>(undefined);
  const [filter,      setFilter]      = useState<'all' | 'COMPRAR' | 'VENDER' | 'ESPERAR'>('all');
  const [refreshKey,  setRefreshKey]  = useState(0);

  const handleUse = (p: TransactionPreset) => {
    setPreset(p);
    setFormOpen(true);
  };

  return (
    <Box p={3}>
      {/* ── Header ── */}
      <Box display="flex" justifyContent="space-between" alignItems="flex-start" mb={3}>
        <Box>
          <Box display="flex" alignItems="center" gap={1.5} mb={0.5}>
            <Box sx={{
              width: 40, height: 40, borderRadius: '12px',
              bgcolor: alpha(TOKENS.blue, 0.1),
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: TOKENS.blue,
            }}>
              <Psychology fontSize="medium" />
            </Box>
            <Typography variant="h4" fontWeight={700}>Motor de Decisiones</Typography>
          </Box>
          <Typography variant="body2" color="text.secondary" ml={7}>
            Recomendaciones AI en tiempo real · actualización automática cada 30 s
          </Typography>
        </Box>
        <Tooltip title="Forzar actualización">
          <IconButton onClick={() => setRefreshKey(k => k + 1)}>
            <Refresh />
          </IconButton>
        </Tooltip>
      </Box>

      {/* ── Leyenda / guía de uso ── */}
      <Alert
        severity="info"
        icon={<Lightbulb />}
        sx={{ mb: 3 }}
        action={
          <Button
            size="small"
            variant="outlined"
            startIcon={<SwapHoriz />}
            onClick={() => setFormOpen(true)}
          >
            Nueva transacción
          </Button>
        }
      >
        Selecciona una divisa, analiza la recomendación y pulsa <strong>USAR RECOMENDACIÓN</strong> para
        pre-llenar el formulario de transacción con el tipo de cambio sugerido por el motor AI.
      </Alert>

      {/* ── Filtro por señal ── */}
      <Box display="flex" gap={1} mb={3} flexWrap="wrap" alignItems="center">
        <Typography variant="caption" color="text.secondary" fontWeight={600} textTransform="uppercase" letterSpacing={0.5}>
          Filtrar por señal:
        </Typography>
        {(['all', 'COMPRAR', 'VENDER', 'ESPERAR'] as const).map(f => (
          <Chip
            key={f}
            label={f === 'all' ? 'Todas' : f}
            onClick={() => setFilter(f)}
            variant={filter === f ? 'filled' : 'outlined'}
            color={
              f === 'COMPRAR' ? 'success' :
              f === 'VENDER'  ? 'error'   :
              f === 'ESPERAR' ? 'warning' : 'default'
            }
            icon={
              f === 'COMPRAR' ? <TrendingUp /> :
              f === 'VENDER'  ? <TrendingDown /> :
              f === 'ESPERAR' ? <Remove /> :
              undefined
            }
            size="small"
          />
        ))}
      </Box>

      {/* ── Divisas: descripción general ── */}
      <Grid container spacing={2} mb={3}>
        {CURRENCIES.map(c => (
          <Grid item xs={6} sm={4} md={2} key={c}>
            <Box sx={{
              p: 1.5, borderRadius: 2, border: `1px solid`,
              borderColor: 'divider',
              textAlign: 'center',
              cursor: 'pointer',
              transition: 'all 0.2s',
              '&:hover': { borderColor: TOKENS.blue, bgcolor: alpha(TOKENS.blue, 0.03) },
            }}>
              <Typography fontSize={20}>{FLAGS[c]}</Typography>
              <Typography variant="caption" fontWeight={700}>{c}</Typography>
            </Box>
          </Grid>
        ))}
      </Grid>

      <Divider sx={{ mb: 3 }} />

      {/* ── Decision Cards grid ── */}
      <Box
        key={refreshKey}
        sx={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
          gap: 2,
        }}
      >
        {CURRENCIES.map(c => (
          <DecisionCard
            key={`${c}-${refreshKey}`}
            currency={c}
            onUseRecommendation={handleUse}
            compact={false}
          />
        ))}
      </Box>

      {/* ── Ayuda al final ── */}
      <Card sx={{ mt: 3, bgcolor: alpha(TOKENS.blue, 0.03), border: `1px solid ${alpha(TOKENS.blue, 0.15)}` }}>
        <CardContent>
          <Typography variant="subtitle2" fontWeight={700} mb={1.5} color={TOKENS.blue}>
            <Psychology sx={{ mr: 0.5, verticalAlign: 'middle', fontSize: 18 }} />
            ¿Cómo interpreta el Motor AI?
          </Typography>
          <Grid container spacing={2}>
            {[
              { signal: 'COMPRAR', color: TOKENS.green, desc: 'El precio de mercado está por debajo del promedio histórico y el spread es favorable. Conviene comprar divisa ahora para vender después a mayor precio.' },
              { signal: 'VENDER',  color: TOKENS.red,   desc: 'El precio de mercado está por encima del promedio histórico. Conviene vender inventario actual y capturar el spread favorable.' },
              { signal: 'ESPERAR', color: TOKENS.amber,  desc: 'El mercado está estable o tiene alta volatilidad. El riesgo no justifica la operación en este momento.' },
            ].map(({ signal, color, desc }) => (
              <Grid item xs={12} md={4} key={signal}>
                <Box display="flex" gap={1} alignItems="flex-start">
                  <Chip label={signal} size="small" sx={{ bgcolor: color, color: '#fff', fontWeight: 700, flexShrink: 0 }} />
                  <Typography variant="caption" color="text.secondary">{desc}</Typography>
                </Box>
              </Grid>
            ))}
          </Grid>
        </CardContent>
      </Card>

      {/* ── Transaction form pre-llenado ── */}
      <TransactionForm
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onSuccess={() => setRefreshKey(k => k + 1)}
        preset={preset}
      />
    </Box>
  );
};

export default DecisionesPage;
