// src/components/transactions/TransactionForm.tsx
import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, TextField, FormControl, InputLabel, Select,
  MenuItem, InputAdornment, Typography, Box, Alert, Divider,
  ToggleButton, ToggleButtonGroup, Chip, Paper, CircularProgress,
  Autocomplete, Stepper, Step, StepLabel, IconButton,
} from '@mui/material';
import {
  SwapHoriz, ArrowUpward, ArrowDownward, Close,
  CheckCircle, Person, Warning, LockOutlined, AssignmentInd,
} from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import { NumericFormat } from 'react-number-format';
import { api } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { formatCurrency } from '../../utils/formatters';
import { isScaled, formatScale, realAmount, formatRateLabel } from '../../utils/finance';
import { TOKENS } from '../../styles/theme';
import { alpha } from '@mui/material/styles';

export interface TransactionPreset {
  currency: string;
  txType:   'BUY' | 'SELL';
  rate:     number;
}

interface Props {
  open:      boolean;
  onClose:   () => void;
  onSuccess: () => void;
  /** When set, the form opens pre-filled (e.g. from a DecisionCard recommendation) */
  preset?:   TransactionPreset;
}

// STEPS is now computed inside the component — see `steps` derived value below.

const CURRENCIES_LIST = [
  { code: 'USD', name: 'Dólar EE.UU.',    flag: '🇺🇸' },
  { code: 'EUR', name: 'Euro',             flag: '🇪🇺' },
  { code: 'CLP', name: 'Peso Chileno',     flag: '🇨🇱' },
  { code: 'PEN', name: 'Sol Peruano',      flag: '🇵🇪' },
  { code: 'BRL', name: 'Real Brasileño',   flag: '🇧🇷' },
  { code: 'ARS', name: 'Peso Argentino',   flag: '🇦🇷' },
];

const PAYMENT_METHODS = [
  { value: 'CASH',     label: 'Efectivo',       icon: '💵' },
  { value: 'QR',       label: 'QR',             icon: '📱' },
  { value: 'TRANSFER', label: 'Transferencia',  icon: '🏦' },
  { value: 'CHECK',    label: 'Cheque',         icon: '📝' },
  { value: 'CARD',     label: 'Tarjeta',        icon: '💳' },
];

const DOC_TYPES = ['CI', 'NIT', 'PASSPORT', 'RUC'];

const TransactionForm: React.FC<Props> = ({ open, onClose, onSuccess, preset }) => {
  const [step,          setStep]          = useState(0);
  const [txType,        setTxType]        = useState<'BUY'|'SELL'>('SELL');
  const [currency,      setCurrency]      = useState('USD');
  const [amount,        setAmount]        = useState<number | undefined>(undefined);
  const [rate,          setRate]          = useState<number | undefined>(undefined);
  const [payMethod,     setPayMethod]     = useState('CASH');
  const [payRef,        setPayRef]        = useState('');
  const [notes,         setNotes]         = useState('');
  const [docType,       setDocType]       = useState('CI');
  const [docNumber,     setDocNumber]     = useState('');
  const [customerName,  setCustomerName]  = useState('');
  const [phone,         setPhone]         = useState('');
  const [customers,     setCustomers]     = useState<any[]>([]);
  const [selectedCust,  setSelectedCust]  = useState<any>(null);
  const [rates,         setRates]         = useState<Record<string, any>>({});
  // scale_factor derivado de la divisa seleccionada (1 para USD/EUR, 1000 para CLP/ARS)
  const scaleFactor = rates[currency]?.scale_factor ?? 1;
  const [wacMap,        setWacMap]        = useState<Record<string, number>>({});
  const [searching,     setSearching]     = useState(false);
  const [loading,       setLoading]       = useState(false);
  const [isReportable,  setIsReportable]  = useState(false); // default: INTERNA
  const [errors,        setErrors]        = useState<Record<string, string>>({});
  const [success,       setSuccess]       = useState<string | null>(null);
  const docRef = useRef<HTMLInputElement>(null);
  const amountRef = useRef<HTMLInputElement>(null);
  const { enqueueSnackbar } = useSnackbar();

  const total = (amount ?? 0) * (rate ?? 0);
  const requiresAuth = total > 35000; // ~$5000 USD equiv in BOB

  // Ganancia estimada: solo aplica en SELL (vendemos divisa al cliente)
  // Ganancia = (TC venta - WAC) × cantidad
  const wac = wacMap[currency];
  const gananciaEstimada: number | null =
    txType === 'SELL' && wac && wac > 0 && rate && amount
      ? (rate - wac) * (amount / scaleFactor)
      : null;

  // Dynamic steps: "Interna" skips the Cliente step entirely.
  const steps    = isReportable ? ['Cliente', 'Operación', 'Confirmar'] : ['Operación', 'Confirmar'];
  const operStep = isReportable ? 1 : 0;   // index of the Operación step
  const confStep = isReportable ? 2 : 1;   // index of the Confirmar step

  // ── Load on open ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!open) return;
    resetForm();
    // Apply preset values — overrides the defaults set in resetForm()
    if (preset) {
      setTxType(preset.txType);
      setCurrency(preset.currency);
      setRate(preset.rate);
    }
    Promise.all([
      api.get('/customers/').catch(() => ({ data: { results: [] } })),
      api.get('/rates/exchange-rates/current/').catch(() => ({ data: [] })),
      api.get('/inventory/').catch(() => ({ data: [] })),
    ]).then(([custRes, ratesRes, invRes]) => {
      setCustomers(custRes.data?.results ?? custRes.data ?? []);
      const rateData = ratesRes.data?.results ?? ratesRes.data ?? [];
      const rateMap: Record<string, any> = {};
      if (Array.isArray(rateData)) {
        rateData.forEach((r: any) => {
          const code = r.currency_from?.code ?? r.currency_from;
          if (code) rateMap[code] = {
            buy:          parseFloat(r.buy_rate),
            sell:         parseFloat(r.sell_rate),
            scale_factor: r.currency_from?.scale_factor ?? r.scale_factor ?? 1,
          };
        });
      }
      setRates(rateMap);
      // WAC por divisa para estimar ganancia en ventas
      const invData = invRes.data?.results ?? invRes.data ?? [];
      const wac: Record<string, number> = {};
      if (Array.isArray(invData)) {
        invData.forEach((inv: any) => {
          const code = inv.currency?.code ?? inv.currency;
          const w = parseFloat(inv.average_cost ?? inv.wac ?? 0);
          if (code && w > 0) wac[code] = w;
        });
      }
      setWacMap(wac);
    });
  }, [open, preset]);

  // ── Auto-set rate on currency/type change ────────────────────────────────────
  // Skip if a preset rate was provided — the user can still override it manually.
  useEffect(() => {
    if (preset?.rate && preset.currency === currency) return;
    if (rates[currency]) {
      // SELL = vendemos divisa al cliente → tasa de venta; BUY = compramos al cliente → tasa de compra
      const r = txType === 'SELL' ? rates[currency].sell : rates[currency].buy;
      setRate(r || undefined);
    }
  }, [currency, txType, rates, preset]);

  // ── Customer search by document ─────────────────────────────────────────────
  const searchCustomer = useCallback(async (doc: string) => {
    if (doc.length < 5) return;
    setSearching(true);
    try {
      const res = await api.get(`/customers/search/?document=${doc}`);
      if (res.data) {
        setSelectedCust(res.data);
        setCustomerName(res.data.full_name);
        setDocType(res.data.document_type);
        setPhone(res.data.phone || '');
        setErrors(p => ({ ...p, customerName: '', docNumber: '' }));
      }
    } catch { /* No encontrado — nuevo cliente */ }
    finally { setSearching(false); }
  }, []);

  // ── Validation per step ──────────────────────────────────────────────────────
  const validateStep = (s: number): boolean => {
    const errs: Record<string, string> = {};
    // Cliente step only exists (and is only required) when isReportable
    if (isReportable && s === 0) {
      if (!docNumber.trim()) errs.docNumber = 'Ingresa el número de documento';
      if (!customerName.trim()) errs.customerName = 'Ingresa el nombre del cliente';
    }
    if (s === operStep) {
      if (!amount || amount <= 0) errs.amount = 'Ingresa un monto válido';
      else if (!Number.isInteger(amount)) errs.amount = 'Solo se permiten números enteros';
      else if (amount > 500000) errs.amount = 'Monto demasiado alto — verifica';
      if (!rate || rate <= 0) errs.rate = 'La tasa de cambio es requerida';
    }
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleNext = () => {
    if (validateStep(step)) setStep(s => s + 1);
  };

  // ── Submit ────────────────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    if (!validateStep(operStep)) { setStep(operStep); return; }
    setLoading(true);
    try {
      const payload = {
        transaction_type:     txType,
        // transaction_category drives visible_asfi server-side — never send is_reportable_to_asfi
        transaction_category: isReportable ? 'REPORTABLE' : 'INTERNA',
        // REPORTABLE: attach customer data; INTERNA: omit customer entirely
        ...(isReportable && {
          customer: selectedCust
            ? { id: selectedCust.id }
            : { document_type: docType, document_number: docNumber, full_name: customerName, phone: phone || '' },
        }),
        currency_from:     currency,
        currency_to:       'BOB',
        amount_from:       Math.round(amount!),           // integer required by backend
        amount_to:         Math.round(total),             // integer required by backend
        exchange_rate:     rate,
        payment_method:    payMethod,
        payment_reference: payRef || '',
        notes:             notes || '',
      };
      const res = await api.post('/transactions/', payload);
      const txNum = res.data?.transaction_number ?? res.data?.id;
      setSuccess(txNum ? `Transacción ${txNum} registrada` : 'Transacción registrada');
      enqueueSnackbar('Transacción registrada exitosamente', { variant: 'success' });
      setTimeout(() => {
        resetForm();
        onSuccess();
        onClose();
      }, 1800);
    } catch (e: any) {
      const errData = e.response?.data;
      let msg = 'Error al registrar la transacción';
      if (typeof errData === 'object' && errData !== null) {
        // Backend returns { code, message, field_errors } or { field: [msgs] }
        if (errData.message) {
          msg = errData.message;
        } else if (errData.field_errors) {
          msg = Object.entries(errData.field_errors as Record<string, any>)
            .map(([f, m]) => Array.isArray(m) ? `${f}: ${m[0]}` : `${f}: ${m}`)
            .join(' · ');
        } else {
          msg = Object.entries(errData)
            .filter(([k]) => k !== 'code')
            .map(([f, m]) => Array.isArray(m) ? `${f}: ${m[0]}` : `${f}: ${m}`)
            .join(' · ');
        }
      }
      enqueueSnackbar(msg, { variant: 'error', persist: false });
      setStep(1); // Volver al paso de operación
    } finally {
      setLoading(false);
    }
  };

  const resetForm = () => {
    setStep(0); setTxType('SELL'); setCurrency('USD');
    setAmount(undefined); setRate(undefined); setPayMethod('CASH');
    setPayRef(''); setNotes(''); setDocType('CI'); setDocNumber('');
    setCustomerName(''); setPhone(''); setSelectedCust(null);
    setIsReportable(false); // default: INTERNA
    setErrors({}); setSuccess(null); setSearching(false);
  };

  const handleClose = () => { resetForm(); onClose(); };

  // ── Step 0: Cliente ──────────────────────────────────────────────────────────
  const stepCliente = (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
      <Autocomplete
        options={customers}
        getOptionLabel={o => `${o.full_name} — ${o.document_number}`}
        value={selectedCust}
        onChange={(_, v) => {
          setSelectedCust(v);
          if (v) { setCustomerName(v.full_name); setDocType(v.document_type); setDocNumber(v.document_number); setPhone(v.phone || ''); }
          else { setCustomerName(''); setDocNumber(''); setPhone(''); }
        }}
        renderInput={params => (
          <TextField {...params} label="Buscar cliente registrado (opcional)"
            InputProps={{ ...params.InputProps, startAdornment: <><Person sx={{ color: TOKENS.muted, mr: 1 }} fontSize="small" />{params.InputProps.startAdornment}</> }} />
        )}
        renderOption={(props, o) => (
          <Box component="li" {...props} sx={{ gap: 1 }}>
            <Box>
              <Typography variant="body2" fontWeight={600}>{o.full_name}</Typography>
              <Typography variant="caption" color="text.secondary">{o.document_type} {o.document_number}{o.is_frequent ? ' ⭐' : ''}{o.is_pep ? ' 🔴 PEP' : ''}</Typography>
            </Box>
          </Box>
        )}
      />

      {!selectedCust && (
        <>
          <Divider>O registrar nuevo cliente</Divider>
          <Box sx={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: 2 }}>
            <FormControl>
              <InputLabel>Tipo Doc.</InputLabel>
              <Select value={docType} label="Tipo Doc." onChange={e => setDocType(e.target.value)}>
                {DOC_TYPES.map(t => <MenuItem key={t} value={t}>{t}</MenuItem>)}
              </Select>
            </FormControl>
            <TextField
              label="Número de documento *"
              value={docNumber}
              inputRef={docRef}
              error={!!errors.docNumber}
              helperText={errors.docNumber}
              onChange={e => { setDocNumber(e.target.value); searchCustomer(e.target.value); }}
              InputProps={{ endAdornment: searching && <CircularProgress size={16} sx={{ mr: 1 }} /> }}
            />
          </Box>
          <TextField
            label="Nombre completo *"
            value={customerName}
            error={!!errors.customerName}
            helperText={errors.customerName}
            onChange={e => setCustomerName(e.target.value)}
          />
          <TextField
            label="Teléfono (Opcional)"
            value={phone}
            onChange={e => setPhone(e.target.value)}
            inputProps={{ inputMode: 'tel' }}
          />
        </>
      )}

      {selectedCust && (
        <Paper sx={{ p: 2, bgcolor: alpha(TOKENS.green, 0.05), border: `1px solid ${alpha(TOKENS.green, 0.2)}` }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <CheckCircle sx={{ color: TOKENS.green, fontSize: 20 }} />
            <Box flex={1}>
              <Typography variant="body2" fontWeight={700}>{selectedCust.full_name}</Typography>
              <Typography variant="caption" color="text.secondary">
                {selectedCust.document_type} {selectedCust.document_number}
                {selectedCust.is_frequent && <Chip label="Frecuente" size="small" color="primary" sx={{ ml: 0.75, height: 16, fontSize: '0.6rem' }} />}
                {selectedCust.is_pep && <Chip label="PEP" size="small" color="error" sx={{ ml: 0.75, height: 16, fontSize: '0.6rem' }} />}
              </Typography>
            </Box>
            <IconButton size="small" onClick={() => { setSelectedCust(null); setCustomerName(''); setDocNumber(''); setPhone(''); }}>
              <Close fontSize="small" />
            </IconButton>
          </Box>
        </Paper>
      )}
    </Box>
  );

  // ── Step 1: Operación ────────────────────────────────────────────────────────
  const stepOperacion = (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
      {/* Tipo */}
      <ToggleButtonGroup value={txType} exclusive fullWidth
        onChange={(_, v) => { if (v) setTxType(v); }}
        sx={{ height: 48 }}>
        <ToggleButton value="SELL" sx={{
          flex: 1, fontWeight: 700, fontSize: '0.875rem', gap: 0.75, border: '1.5px solid',
          '&.Mui-selected': { bgcolor: alpha(TOKENS.blue, 0.1), color: TOKENS.blue, borderColor: TOKENS.blue },
        }}>
          <ArrowUpward fontSize="small" /> Cliente compra divisas
        </ToggleButton>
        <ToggleButton value="BUY" sx={{
          flex: 1, fontWeight: 700, fontSize: '0.875rem', gap: 0.75, border: '1.5px solid',
          '&.Mui-selected': { bgcolor: alpha(TOKENS.green, 0.1), color: TOKENS.green, borderColor: TOKENS.green },
        }}>
          <ArrowDownward fontSize="small" /> Cliente vende divisas
        </ToggleButton>
      </ToggleButtonGroup>

      {/* Divisa */}
      <Box>
        <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ mb: 1, display: 'block', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Divisa
        </Typography>
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          {CURRENCIES_LIST.map(c => (
            <Chip
              key={c.code}
              label={`${c.flag} ${c.code}`}
              onClick={() => setCurrency(c.code)}
              variant={currency === c.code ? 'filled' : 'outlined'}
              color={currency === c.code ? 'primary' : 'default'}
              sx={{ fontWeight: 700, cursor: 'pointer', fontSize: '0.8125rem', height: 34 }}
            />
          ))}
        </Box>
      </Box>

      {/* Monto + Tasa */}
      <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2 }}>
        <NumericFormat
          customInput={TextField}
          label={isScaled(scaleFactor)
            ? `Lotes de ${formatScale(scaleFactor)} ${currency} *`
            : `Monto en ${currency} *`}
          value={amount}
          onValueChange={v => {
            // Enforce integer-only: discard any fractional part
            const raw = v.floatValue;
            setAmount(raw !== undefined ? Math.trunc(raw) : undefined);
          }}
          thousandSeparator=","
          decimalScale={0}
          allowNegative={false}
          inputRef={amountRef}
          error={!!errors.amount}
          helperText={errors.amount || (isScaled(scaleFactor) && amount
            ? `= ${new Intl.NumberFormat('es-BO').format(realAmount(amount, scaleFactor))} ${currency} reales`
            : undefined)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <Typography variant="caption" fontWeight={700} color="text.secondary">
                  {isScaled(scaleFactor) ? `×${formatScale(scaleFactor)}` : currency}
                </Typography>
              </InputAdornment>
            ),
          }}
          sx={{ '& input': { fontVariantNumeric: 'tabular-nums', fontWeight: 600, fontSize: '1rem' } }}
        />
        <NumericFormat
          customInput={TextField}
          label={isScaled(scaleFactor) ? `TC por ${formatScale(scaleFactor)} ${currency} *` : 'Tasa de Cambio *'}
          value={rate}
          onValueChange={v => setRate(v.floatValue)}
          decimalScale={4}
          fixedDecimalScale
          allowNegative={false}
          error={!!errors.rate}
          helperText={errors.rate}
          InputProps={{
            endAdornment: rates[currency] && (
              <InputAdornment position="end">
                <Chip
                  label={`Mercado: ${(txType === 'SELL' ? rates[currency]?.sell : rates[currency]?.buy)?.toFixed(4)}`}
                  size="small"
                  onClick={() => setRate(txType === 'SELL' ? rates[currency]?.sell : rates[currency]?.buy)}
                  sx={{ cursor: 'pointer', fontSize: '0.625rem', height: 20 }}
                />
              </InputAdornment>
            ),
          }}
          sx={{ '& input': { fontVariantNumeric: 'tabular-nums', fontWeight: 600, fontSize: '1rem' } }}
        />
      </Box>

      {/* Total preview */}
      {total > 0 && (
        <Paper sx={{
          p: 2.5, textAlign: 'center',
          bgcolor: txType === 'SELL' ? alpha(TOKENS.blue, 0.05) : alpha(TOKENS.green, 0.05),
          border: `1.5px solid ${txType === 'SELL' ? alpha(TOKENS.blue, 0.2) : alpha(TOKENS.green, 0.2)}`,
        }}>
          <Typography variant="overline" color="text.secondary">TOTAL EN BOLIVIANOS</Typography>
          <Typography variant="h4" fontWeight={800}
            sx={{ color: txType === 'SELL' ? TOKENS.blue : TOKENS.green, fontVariantNumeric: 'tabular-nums' }}>
            {formatCurrency(total)}
          </Typography>
          {/* Desglose adaptado a escala */}
          {isScaled(scaleFactor) ? (
            <Typography variant="caption" color="text.secondary">
              {amount ?? 0} lotes × BOB {rate?.toFixed(4) ?? '0'}/{formatScale(scaleFactor)} {currency}
              {' = '}{Math.round(total)} BOB
              {' · '}{new Intl.NumberFormat('es-BO').format(realAmount(amount ?? 0, scaleFactor))} {currency} reales
            </Typography>
          ) : (
            <Typography variant="caption" color="text.secondary">
              {amount ?? 0} {currency} × BOB {rate?.toFixed(4) ?? '0'} = {Math.round(total)} BOB
            </Typography>
          )}
          {/* Ganancia estimada en tiempo real */}
          {gananciaEstimada !== null && (
            <Box sx={{
              mt: 1.5, pt: 1.5,
              borderTop: `1px dashed ${gananciaEstimada >= 0 ? alpha(TOKENS.green, 0.4) : alpha(TOKENS.red, 0.4)}`,
            }}>
              <Typography variant="caption" color="text.secondary" fontWeight={600} textTransform="uppercase" letterSpacing={0.5}>
                Ganancia estimada
              </Typography>
              <Typography variant="h6" fontWeight={800}
                sx={{ color: gananciaEstimada >= 0 ? TOKENS.green : TOKENS.red, fontVariantNumeric: 'tabular-nums' }}>
                {gananciaEstimada >= 0 ? '+' : ''}{formatCurrency(gananciaEstimada)}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                TC venta {rate?.toFixed(4)} − WAC {wac?.toFixed(4)} = margen {(rate! - wac!).toFixed(4)}/u
              </Typography>
            </Box>
          )}
          {requiresAuth && (
            <Box sx={{ mt: 1.5 }}>
              <Chip icon={<Warning />} label="Requiere autorización de supervisor (>Bs 35,000)" color="warning" size="small" />
            </Box>
          )}
        </Paper>
      )}

      {/* Método de pago */}
      <Box>
        <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ mb: 1, display: 'block', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Método de Pago
        </Typography>
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          {PAYMENT_METHODS.map(m => (
            <Paper
              key={m.value}
              onClick={() => setPayMethod(m.value)}
              sx={{
                px: 1.75, py: 1, cursor: 'pointer', borderRadius: '8px', transition: 'all 0.15s',
                border: `1.5px solid ${payMethod === m.value ? TOKENS.blue : TOKENS.border}`,
                bgcolor: payMethod === m.value ? alpha(TOKENS.blue, 0.06) : TOKENS.surface,
                display: 'flex', alignItems: 'center', gap: 0.75,
                '&:hover': { borderColor: TOKENS.blue },
              }}
            >
              <Typography sx={{ fontSize: 16, lineHeight: 1 }}>{m.icon}</Typography>
              <Typography variant="caption" fontWeight={700}
                sx={{ color: payMethod === m.value ? TOKENS.blue : TOKENS.textSub }}>
                {m.label}
              </Typography>
            </Paper>
          ))}
        </Box>
      </Box>

      {(payMethod === 'TRANSFER' || payMethod === 'CHECK') && (
        <TextField label="Número de referencia" value={payRef}
          onChange={e => setPayRef(e.target.value)}
          placeholder="Nro. transferencia o cheque" />
      )}

      <TextField label="Notas (Opcional)" value={notes}
        onChange={e => setNotes(e.target.value)}
        multiline rows={2} placeholder="Observaciones de la operación…" />

    </Box>
  );

  // ── Step 2: Confirmación ─────────────────────────────────────────────────────
  const curInfo = CURRENCIES_LIST.find(c => c.code === currency);
  const stepConfirm = (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {success ? (
        <Box sx={{ textAlign: 'center', py: 3 }}>
          <CheckCircle sx={{ fontSize: 64, color: TOKENS.green, mb: 2 }} />
          <Typography variant="h5" fontWeight={700} color={TOKENS.green}>{success}</Typography>
        </Box>
      ) : (
        <>
          <Alert severity="warning" icon={<Warning />}>
            Revisa cada dato antes de confirmar — las transacciones afectan el inventario y el capital en tiempo real.
          </Alert>

          {/* Resumen cliente — solo para transacciones reportables */}
          {isReportable ? (
            <Paper sx={{ p: 2 }}>
              <Typography variant="overline" color="text.secondary" mb={1} display="block">Cliente</Typography>
              <Typography variant="body1" fontWeight={700}>{customerName}</Typography>
              <Typography variant="body2" color="text.secondary">{docType} {docNumber}</Typography>
            </Paper>
          ) : (
            <Paper sx={{
              p: 1.5, display: 'flex', alignItems: 'center', gap: 1.5,
              bgcolor: alpha(TOKENS.blue, 0.05),
              border: `1px solid ${alpha(TOKENS.blue, 0.2)}`,
            }}>
              <LockOutlined sx={{ color: TOKENS.blue, fontSize: 20 }} />
              <Box>
                <Typography variant="body2" fontWeight={700} sx={{ color: TOKENS.blue }}>
                  Transacción interna (no reportada a ASFI)
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Sin datos de cliente — excluida del RTE y Libro Diario regulatorio
                </Typography>
              </Box>
            </Paper>
          )}

          {/* Resumen operación */}
          <Paper sx={{ p: 2, bgcolor: alpha(txType === 'SELL' ? TOKENS.blue : TOKENS.green, 0.04) }}>
            <Typography variant="overline" color="text.secondary" mb={1.5} display="block">Operación</Typography>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {[
                { label: 'Tipo', value: txType === 'SELL' ? 'Venta de divisas (cliente compra)' : 'Compra de divisas (cliente vende)' },
                { label: 'Divisa', value: `${curInfo?.flag} ${currency} — ${curInfo?.name}` },
                {
                  label: 'Monto',
                  value: isScaled(scaleFactor)
                    ? `${amount ?? 0} lotes · ${new Intl.NumberFormat('es-BO').format(realAmount(amount ?? 0, scaleFactor))} ${currency} reales`
                    : `${currency} ${amount ?? 0}`,
                  mono: true,
                },
                {
                  label: 'Tasa',
                  value: formatRateLabel(rate ?? 0, currency, scaleFactor),
                  mono: true,
                },
                { label: 'Pago', value: PAYMENT_METHODS.find(m => m.value === payMethod)?.label ?? payMethod },
                { label: 'Categoría', value: isReportable ? '🟢 Reportable (ASFI)' : '🔵 Interna' },
              ].map((row, i) => (
                <Box key={i} sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography variant="body2" color="text.secondary">{row.label}</Typography>
                  <Typography variant="body2" fontWeight={600} sx={row.mono ? { fontVariantNumeric: 'tabular-nums' } : {}}>
                    {row.value}
                  </Typography>
                </Box>
              ))}
            </Box>

            <Divider sx={{ my: 1.5 }} />
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Typography variant="subtitle1" fontWeight={700}>Total a cobrar / pagar</Typography>
              <Typography variant="h5" fontWeight={800}
                sx={{ color: txType === 'SELL' ? TOKENS.blue : TOKENS.green, fontVariantNumeric: 'tabular-nums' }}>
                {formatCurrency(total)}
              </Typography>
            </Box>
          </Paper>

          {requiresAuth && (
            <Alert severity="warning">Esta operación requiere autorización de un supervisor por superar Bs. 35,000.</Alert>
          )}
        </>
      )}
    </Box>
  );

  return (
    <Dialog open={open} onClose={success ? handleClose : undefined} maxWidth="sm" fullWidth
      PaperProps={{ sx: { borderRadius: '16px', maxHeight: '90vh' } }}>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1.5, pb: 1 }}>
        <Box sx={{ width: 36, height: 36, borderRadius: '9px', bgcolor: alpha(TOKENS.blue, 0.1), display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <SwapHoriz sx={{ color: TOKENS.blue, fontSize: 20 }} />
        </Box>
        Nueva Transacción
        <Box flex={1} />
        {!success && (
          <IconButton size="small" onClick={handleClose} sx={{ color: TOKENS.muted }}>
            <Close fontSize="small" />
          </IconButton>
        )}
      </DialogTitle>

      {/* ── Transaction type selector ── */}
      <Box sx={{ px: 3, pt: 0.5, pb: 1.5 }}>
        <ToggleButtonGroup
          value={isReportable ? 'REPORTABLE' : 'INTERNA'}
          exclusive
          fullWidth
          size="small"
          onChange={(_, val) => {
            if (!val) return; // prevent deselection
            const next = val === 'REPORTABLE';
            setIsReportable(next);
            setStep(0); // reset — step indices change between modes
          }}
        >
          <ToggleButton
            value="INTERNA"
            sx={{
              gap: 0.75, fontWeight: 700, fontSize: '0.8rem',
              '&.Mui-selected': {
                bgcolor: alpha(TOKENS.blue, 0.1),
                color: TOKENS.blue,
                borderColor: TOKENS.blue,
              },
            }}
          >
            <LockOutlined fontSize="small" />
            Interna (no ASFI)
          </ToggleButton>
          <ToggleButton
            value="REPORTABLE"
            sx={{
              gap: 0.75, fontWeight: 700, fontSize: '0.8rem',
              '&.Mui-selected': {
                bgcolor: alpha(TOKENS.green, 0.1),
                color: TOKENS.green,
                borderColor: TOKENS.green,
              },
            }}
          >
            <AssignmentInd fontSize="small" />
            Reportable (ASFI)
          </ToggleButton>
        </ToggleButtonGroup>
      </Box>

      <Box sx={{ px: 3, pb: 1.5 }}>
        <Stepper activeStep={step} alternativeLabel>
          {steps.map((label, i) => (
            <Step key={label} completed={i < step}>
              <StepLabel sx={{
                '& .MuiStepLabel-label': { fontSize: '0.75rem', fontWeight: 600 },
                '& .MuiStepIcon-root.Mui-active': { color: TOKENS.blue },
                '& .MuiStepIcon-root.Mui-completed': { color: TOKENS.green },
              }}>
                {label}
              </StepLabel>
            </Step>
          ))}
        </Stepper>
      </Box>

      <DialogContent sx={{ pt: 1.5 }}>
        {isReportable && step === 0 && stepCliente}
        {step === operStep && stepOperacion}
        {step === confStep && stepConfirm}
      </DialogContent>

      {!success && (
        <DialogActions sx={{ px: 3, pb: 2.5, pt: 1 }}>
          <Button onClick={step === 0 ? handleClose : () => setStep(s => s - 1)}
            sx={{ color: TOKENS.textSub }}>
            {step === 0 ? 'Cancelar' : 'Atrás'}
          </Button>
          <Box flex={1} />
          {step < confStep ? (
            <Button variant="contained" onClick={handleNext} sx={{ px: 3 }}>
              Siguiente →
            </Button>
          ) : (
            <Button
              variant="contained"
              color="success"
              onClick={handleSubmit}
              disabled={loading}
              startIcon={loading ? <CircularProgress size={16} color="inherit" /> : <CheckCircle />}
              sx={{ px: 3, fontWeight: 700, minWidth: 160 }}
            >
              {loading ? 'Procesando…' : 'Confirmar operación'}
            </Button>
          )}
        </DialogActions>
      )}
    </Dialog>
  );
};

export default TransactionForm;
