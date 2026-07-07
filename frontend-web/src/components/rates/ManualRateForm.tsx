// src/components/rates/ManualRateForm.tsx
// Formulario inline para crear o editar una tasa manual.
import React, { useEffect, useState } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, Grid, TextField, MenuItem, Alert, Typography,
  CircularProgress, Chip,
} from '@mui/material';
import { Save, Add } from '@mui/icons-material';
import { useFormik } from 'formik';
import * as yup from 'yup';
import { useSnackbar } from 'notistack';
import { ratesApi, ExchangeRate } from '../../services/ratesApi';

// ── Tipos & config ─────────────────────────────────────────────────────────────

const MARKET_TYPES = [
  { value: 'paralelo_digital',            label: 'Paralelo Digital' },
  { value: 'paralelo_fisico_empresa',     label: 'Paralelo Físico — Empresa' },
  { value: 'paralelo_fisico_competencia', label: 'Paralelo Físico — Competencia' },
];

const CURRENCIES = ['USD', 'EUR', 'BRL', 'PEN', 'CLP', 'ARS', 'GBP', 'CNY'];

const validationSchema = yup.object({
  currency_code: yup.string().required('Selecciona una divisa'),
  buy_rate:      yup.number().typeError('Número requerido').min(0.0001, 'Debe ser > 0').required('Requerido'),
  sell_rate:     yup.number().typeError('Número requerido').min(0.0001, 'Debe ser > 0').required('Requerido')
                    .when('buy_rate', (buy, schema) =>
                      schema.min(yup.ref('buy_rate'), 'Venta debe ser ≥ Compra')
                    ),
  market_type:   yup.string().required('Selecciona el tipo de mercado'),
});

// ── ManualRateForm ─────────────────────────────────────────────────────────────

interface ManualRateFormProps {
  open:         boolean;
  editingRate?: ExchangeRate | null;
  onClose:      (saved: boolean) => void;
}

const ManualRateForm: React.FC<ManualRateFormProps> = ({ open, editingRate, onClose }) => {
  const { enqueueSnackbar }    = useSnackbar();
  const [currencies, setCurrencies] = useState<{ code: string; name: string }[]>([]);
  const isEditing = Boolean(editingRate);

  // Cargar divisas disponibles
  useEffect(() => {
    if (!open) return;
    ratesApi.getCurrencies()
      .then(data => setCurrencies(data.filter((c: any) => c.code !== 'BOB')))
      .catch(() => {
        // Fallback a lista estática
        setCurrencies(CURRENCIES.map(c => ({ code: c, name: c })));
      });
  }, [open]);

  const formik = useFormik({
    initialValues: {
      currency_code: editingRate?.currency_from?.code ?? 'USD',
      buy_rate:      editingRate ? parseFloat(editingRate.buy_rate).toString() : '',
      sell_rate:     editingRate ? parseFloat(editingRate.sell_rate).toString() : '',
      market_type:   editingRate?.market_type ?? 'paralelo_digital',
    },
    enableReinitialize: true,
    validationSchema,
    onSubmit: async (values, helpers) => {
      try {
        const buy  = parseFloat(values.buy_rate);
        const sell = parseFloat(values.sell_rate);
        const official = ((buy + sell) / 2).toFixed(4);

        if (isEditing && editingRate) {
          await ratesApi.updateRate(editingRate.id, {
            buy_rate:      values.buy_rate,
            sell_rate:     values.sell_rate,
            official_rate: official,
            market_type:   values.market_type,
            source_method: 'MANUAL',
            is_validated:  true,
            valid_from:    new Date().toISOString(),
          } as any);
          enqueueSnackbar('Tasa actualizada correctamente', { variant: 'success' });
        } else {
          // Para crear, necesitamos los IDs de las divisas — usamos la API con el código
          await ratesApi.createRate({
            buy_rate:      values.buy_rate,
            sell_rate:     values.sell_rate,
            official_rate: official,
            market_type:   values.market_type,
            source_method: 'MANUAL',
            is_validated:  true,
            valid_from:    new Date().toISOString(),
            // El backend acepta currency_from_code si el serializer lo soporta
            ...(({ currency_code: values.currency_code }) as any),
          } as any);
          enqueueSnackbar('Tasa manual creada correctamente', { variant: 'success' });
        }
        helpers.resetForm();
        onClose(true);
      } catch (e: any) {
        const msg = e?.response?.data
          ? Object.values(e.response.data).flat().join(' · ')
          : 'Error al guardar la tasa';
        enqueueSnackbar(msg, { variant: 'error' });
      }
    },
  });

  const buy  = parseFloat(formik.values.buy_rate)  || 0;
  const sell = parseFloat(formik.values.sell_rate) || 0;
  const spread    = sell - buy;
  const spreadPct = buy > 0 ? ((spread / buy) * 100) : 0;

  return (
    <Dialog
      open={open}
      onClose={() => { formik.resetForm(); onClose(false); }}
      maxWidth="sm"
      fullWidth
    >
      <DialogTitle sx={{ pb: 1 }}>
        <Typography fontWeight={800} fontSize="1.05rem">
          {isEditing ? 'Editar Tasa Manual' : 'Nueva Tasa Manual'}
        </Typography>
        {isEditing && editingRate && (
          <Typography variant="caption" color="text.secondary" display="block">
            {editingRate.currency_from?.code}/{editingRate.currency_to?.code}
            {editingRate.source_method === 'INFERENCE' && (
              <Chip label="INFERIDA — al guardar quedará MANUAL y validada" size="small" color="error" sx={{ ml: 1, fontSize: '0.6rem', height: 18 }} />
            )}
          </Typography>
        )}
      </DialogTitle>

      <DialogContent dividers>
        <Grid container spacing={2}>
          {/* Divisa (solo en creación) */}
          {!isEditing && (
            <Grid item xs={12} sm={6}>
              <TextField
                select fullWidth size="small"
                label="Divisa"
                name="currency_code"
                value={formik.values.currency_code}
                onChange={formik.handleChange}
                error={formik.touched.currency_code && Boolean(formik.errors.currency_code)}
                helperText={formik.touched.currency_code && formik.errors.currency_code}
              >
                {(currencies.length > 0 ? currencies : CURRENCIES.map(c => ({ code: c, name: c }))).map(c => (
                  <MenuItem key={c.code} value={c.code}>{c.code} — {c.name}</MenuItem>
                ))}
              </TextField>
            </Grid>
          )}

          {/* Tipo de mercado */}
          <Grid item xs={12} sm={isEditing ? 12 : 6}>
            <TextField
              select fullWidth size="small"
              label="Tipo de mercado"
              name="market_type"
              value={formik.values.market_type}
              onChange={formik.handleChange}
              error={formik.touched.market_type && Boolean(formik.errors.market_type)}
              helperText={formik.touched.market_type && formik.errors.market_type}
            >
              {MARKET_TYPES.map(m => (
                <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>
              ))}
            </TextField>
          </Grid>

          {/* Tasa compra */}
          <Grid item xs={6}>
            <TextField
              fullWidth size="small"
              label="Tasa de Compra (BOB)"
              name="buy_rate"
              type="number"
              inputProps={{ step: '0.0001', min: '0' }}
              value={formik.values.buy_rate}
              onChange={formik.handleChange}
              onBlur={formik.handleBlur}
              error={formik.touched.buy_rate && Boolean(formik.errors.buy_rate)}
              helperText={formik.touched.buy_rate && formik.errors.buy_rate}
              placeholder="Ej: 6.9500"
            />
          </Grid>

          {/* Tasa venta */}
          <Grid item xs={6}>
            <TextField
              fullWidth size="small"
              label="Tasa de Venta (BOB)"
              name="sell_rate"
              type="number"
              inputProps={{ step: '0.0001', min: '0' }}
              value={formik.values.sell_rate}
              onChange={formik.handleChange}
              onBlur={formik.handleBlur}
              error={formik.touched.sell_rate && Boolean(formik.errors.sell_rate)}
              helperText={formik.touched.sell_rate && formik.errors.sell_rate}
              placeholder="Ej: 7.0500"
            />
          </Grid>

          {/* Preview de spread */}
          {buy > 0 && sell > 0 && (
            <Grid item xs={12}>
              <Alert
                severity={spreadPct > 5 ? 'warning' : 'info'}
                sx={{ py: 0.5, fontSize: '0.75rem' }}
              >
                Tasa oficial (mid-point): <strong>{((buy + sell) / 2).toFixed(4)}</strong>
                {' · '}
                Spread: <strong>{spread.toFixed(4)} BOB ({spreadPct.toFixed(2)}%)</strong>
                {spreadPct > 5 && ' ⚠ Spread elevado'}
              </Alert>
            </Grid>
          )}

          {/* Aviso de validación */}
          <Grid item xs={12}>
            <Alert severity="info" sx={{ py: 0.5 }}>
              Al guardar: fuente → <strong>MANUAL</strong> · validated → <strong>true</strong>
              {isEditing && ' · valid_from actualizado a ahora'}
            </Alert>
          </Grid>
        </Grid>
      </DialogContent>

      <DialogActions sx={{ px: 3, py: 1.5, gap: 1 }}>
        <Button
          onClick={() => { formik.resetForm(); onClose(false); }}
          disabled={formik.isSubmitting}
        >
          Cancelar
        </Button>
        <Button
          variant="contained"
          color="warning"
          onClick={() => formik.submitForm()}
          disabled={formik.isSubmitting || !formik.dirty}
          startIcon={formik.isSubmitting
            ? <CircularProgress size={16} color="inherit" />
            : isEditing ? <Save /> : <Add />}
          sx={{ fontWeight: 700 }}
        >
          {formik.isSubmitting
            ? 'Guardando…'
            : isEditing ? 'Guardar y Validar' : 'Crear Tasa Manual'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default ManualRateForm;
