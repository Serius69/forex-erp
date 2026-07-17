import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Card, CardContent, Chip, Button, Grid, Alert, CircularProgress,
} from '@mui/material';
import { Refresh, Savings } from '@mui/icons-material';
import { alpha } from '@mui/material/styles';
import { TOKENS } from '../../styles/theme';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';

interface CashVariant {
  buy_rate:          string;
  sell_rate:         string;
  spread_pct:        string;
  buy_discount_pct:  number;
  buy_discount_bob:  number;
}

// ── Cash Variants Panel ───────────────────────────────────────────────────────
const CashVariantsPanel: React.FC = () => {
  const [variants, setVariants]   = useState<Record<string, CashVariant>>({});
  const [loading, setLoading]     = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const { enqueueSnackbar }       = useSnackbar();
  const { user }                  = useAuth();

  const loadVariants = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/rates/cash-variants/');
      setVariants(res.data.variants ?? {});
    } catch {
      enqueueSnackbar('Error al cargar variantes de efectivo', { variant: 'error' });
    } finally { setLoading(false); }
  }, [enqueueSnackbar]);

  useEffect(() => { loadVariants(); }, [loadVariants]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await api.post('/rates/cash-variants/');
      enqueueSnackbar('Recálculo de variantes encolado', { variant: 'success' });
      setTimeout(loadVariants, 3000);
    } catch { enqueueSnackbar('Error al refrescar', { variant: 'error' }); }
    finally { setRefreshing(false); }
  };

  if (loading) return (
    <Box display="flex" justifyContent="center" p={4}>
      <CircularProgress />
    </Box>
  );

  const variantDefs = [
    { code: 'USD',              icon: '💵', name: 'USD Estándar',         desc: 'Billetes 20/50/100 en buen estado', isStandard: true },
    { code: 'USD_CASH_LOOSE',   icon: '💵', name: 'USD Sueltos/Sencillos', desc: 'Billetes de 5 y 10 dólares',       isStandard: false },
    { code: 'USD_SMALL_BILLS',  icon: '🪙', name: 'USD Billetes 1 y 2',   desc: 'Muy baja liquidez en Bolivia',     isStandard: false },
    { code: 'PEN',              icon: '🇵🇪', name: 'PEN Estándar',         desc: 'Billetes sol peruano',             isStandard: true },
    { code: 'PEN_COINS',        icon: '🪙', name: 'PEN Monedas',           desc: 'Monedas sol peruano',              isStandard: false },
  ];

  return (
    <Box>
      <Box display="flex" alignItems="center" justifyContent="space-between" mb={3}>
        <Box>
          <Typography variant="h6" fontWeight={800}>Variantes de Efectivo Físico</Typography>
          <Typography variant="body2" color="text.secondary">
            Tasas diferenciadas según denominación y condición física del billete.
            La casa de cambios aplica descuentos en compra para divisas de baja liquidez.
          </Typography>
        </Box>
        {user?.role === 'ADMIN' && (
          <Button
            variant="outlined" size="small" startIcon={<Refresh />}
            onClick={handleRefresh} disabled={refreshing}
          >
            {refreshing ? 'Recalculando…' : 'Recalcular'}
          </Button>
        )}
      </Box>

      <Alert severity="info" sx={{ mb: 3 }} icon={<Savings />}>
        <strong>Lógica de negocio:</strong> La tasa de <strong>VENTA</strong> es igual al estándar
        (cobramos lo mismo al cliente). La tasa de <strong>COMPRA</strong> es inferior —
        pagamos menos al cliente por billetes de menor liquidez o difícil recolocación en el mercado.
      </Alert>

      <Grid container spacing={2}>
        {variantDefs.map((def) => {
          const v = variants[def.code];
          const isVariant = !def.isStandard;

          return (
            <Grid item xs={12} sm={6} md={4} key={def.code}>
              <Card sx={{
                position: 'relative', overflow: 'hidden',
                border: '1px solid',
                borderColor: isVariant ? alpha('#ff9800', 0.4) : 'divider',
                bgcolor: isVariant ? alpha('#fff8e1', 0.5) : 'white',
              }}>
                <Box sx={{
                  position: 'absolute', top: 0, left: 0, right: 0, height: 3,
                  bgcolor: isVariant ? '#ff9800' : TOKENS.blue,
                }} />
                <CardContent>
                  <Box display="flex" alignItems="center" gap={1} mb={1.5}>
                    <Typography sx={{ fontSize: '1.5rem', lineHeight: 1 }}>{def.icon}</Typography>
                    <Box>
                      <Typography variant="subtitle2" fontWeight={800}>{def.name}</Typography>
                      <Typography variant="caption" color="text.secondary">{def.desc}</Typography>
                    </Box>
                    {isVariant && (
                      <Chip label="VARIANTE" size="small"
                        sx={{ ml: 'auto', bgcolor: alpha('#ff9800', 0.15), color: '#e65100',
                             fontSize: '0.6rem', height: 18, fontWeight: 700 }} />
                    )}
                  </Box>

                  {v ? (
                    <>
                      <Box display="flex" justifyContent="space-between" mb={1}>
                        <Box>
                          <Typography variant="overline" sx={{ fontSize: '0.6rem', color: TOKENS.muted }}>Compra</Typography>
                          <Typography variant="h5" fontWeight={900} color="success.main" sx={{ fontVariantNumeric: 'tabular-nums', lineHeight: 1.1 }}>
                            {parseFloat(v.buy_rate).toFixed(4)}
                          </Typography>
                        </Box>
                        <Box textAlign="right">
                          <Typography variant="overline" sx={{ fontSize: '0.6rem', color: TOKENS.muted }}>Venta</Typography>
                          <Typography variant="h5" fontWeight={900} color="error.main" sx={{ fontVariantNumeric: 'tabular-nums', lineHeight: 1.1 }}>
                            {parseFloat(v.sell_rate).toFixed(4)}
                          </Typography>
                        </Box>
                      </Box>

                      <Box display="flex" justifyContent="space-between" alignItems="center">
                        <Typography variant="caption" color="text.secondary">
                          Spread: <strong>{parseFloat(v.spread_pct).toFixed(2)}%</strong>
                        </Typography>
                        {isVariant && v.buy_discount_pct > 0 && (
                          <Chip
                            label={`Compra -${parseFloat(String(v.buy_discount_pct)).toFixed(1)}%`}
                            size="small"
                            color="warning"
                            sx={{ fontSize: '0.6rem', height: 20, fontWeight: 700 }}
                          />
                        )}
                      </Box>

                      {isVariant && v.buy_discount_bob > 0 && (
                        <Typography variant="caption" color="text.disabled" display="block" mt={0.5}>
                          Descuento: {parseFloat(String(v.buy_discount_bob)).toFixed(4)} BOB/unidad vs estándar
                        </Typography>
                      )}
                    </>
                  ) : (
                    <Typography variant="caption" color="text.disabled" fontStyle="italic">
                      Sin datos disponibles — actualice para calcular
                    </Typography>
                  )}
                </CardContent>
              </Card>
            </Grid>
          );
        })}
      </Grid>
    </Box>
  );
};

export default CashVariantsPanel;
