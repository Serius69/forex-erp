import React, { useState, useEffect } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Grid,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  InputAdornment,
  Typography, 
  Box,
  Stepper,
  Step,
  StepLabel,
  Alert,
  Autocomplete,
  ToggleButton,
  ToggleButtonGroup,
  Chip,
  Paper,
  Divider,
} from '@mui/material';
import {
  AttachMoney,
  Person,
  Calculate,
  Receipt,
  SwapHoriz,
} from '@mui/icons-material';
import { useFormik } from 'formik';
import * as yup from 'yup';
import { useSnackbar } from 'notistack';
import { NumericFormat } from 'react-number-format';

import { api } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import PinDialog from '../common/PinDialog';
import { formatCurrency, formatNumber } from '../../utils/formatters';

interface TransactionFormProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

const validationSchema = yup.object({
  transactionType: yup.string().required('Tipo de transacción requerido'),
  customerId: yup.number().nullable(),
  customerName: yup.string().when('customerId', {
    is:   (val: any) => !val,
    then: (schema: any) => schema.required('Nombre del cliente requerido'),
  }),
  documentNumber: yup.string().when('customerId', {
    is:   (val: any) => !val,
    then: (schema: any) => schema.required('Nombre del cliente requerido'),
  }),
  currencyFrom: yup.string().required('Divisa requerida'),
  amountFrom: yup.number().min(0.01, 'Monto mínimo 0.01').required('Monto requerido'),
  exchangeRate: yup.number().min(0.0001, 'Tasa inválida').required('Tasa requerida'),
  paymentMethod: yup.string().required('Método de pago requerido'),
});

const steps = ['Cliente', 'Transacción', 'Confirmación'];

const TransactionForm: React.FC<TransactionFormProps> = ({ open, onClose, onSuccess }) => {
  const [activeStep, setActiveStep] = useState(0);
  const [customers, setCustomers] = useState<any[]>([]);
  const [rates, setRates] = useState<any>({});
  const [showPinDialog, setShowPinDialog] = useState(false);
  const [loading, setLoading] = useState(false);
  
  const { enqueueSnackbar } = useSnackbar();
  const { verifyPin } = useAuth();

  const formik = useFormik({
    initialValues: {
      transactionType: 'SELL',
      customerId: null,
      customerName: '',
      documentType: 'CI',
      documentNumber: '',
      phone: '',
      email: '',
      currencyFrom: 'USD',
      amountFrom: '',
      exchangeRate: '',
      paymentMethod: 'CASH',
      paymentReference: '',
      notes: '',
    },
    validationSchema,
    onSubmit: async (values) => {
      setShowPinDialog(true);
    },
  });

  useEffect(() => {
    if (open) {
      loadCustomers();
      loadRates();
    }
  }, [open]);

  useEffect(() => {
    // Actualizar tasa cuando cambia la divisa o tipo de transacción
    if (formik.values.currencyFrom && formik.values.transactionType) {
      const rate = rates[formik.values.currencyFrom];
      if (rate) {
        const exchangeRate = formik.values.transactionType === 'BUY' 
          ? rate.sell 
          : rate.buy;
        formik.setFieldValue('exchangeRate', exchangeRate);
      }
    }
  }, [formik.values.currencyFrom, formik.values.transactionType, rates]);

  const loadCustomers = async () => {
    try {
      const response = await api.get('/customers/');
      setCustomers(response.data.results);
    } catch (error) {
      console.error('Error loading customers:', error);
    }
  };

  const loadRates = async () => {
    try {
      const response = await api.get('/rates/exchange-rates/current/');
      setRates(response.data);
    } catch (error) {
      console.error('Error loading rates:', error);
    }
  };

  const searchCustomerByDocument = async (documentNumber: string) => {
    if (documentNumber.length < 5) return;

    try {
      const response = await api.get(`/customers/search/?document=${documentNumber}`);
      if (response.data) {
        formik.setValues({
          ...formik.values,
          customerId: response.data.id,
          customerName: response.data.full_name,
          documentType: response.data.document_type,
          documentNumber: response.data.document_number,
          phone: response.data.phone || '',
          email: response.data.email || '',
        });
      }
    } catch (error) {
      // Cliente no encontrado, permitir registro nuevo
    }
  };

  const handlePinSubmit = async (pin: string) => {
    const isValid = await verifyPin(pin);
    if (!isValid) {
      enqueueSnackbar('PIN inválido', { variant: 'error' });
      return;
    }

    setShowPinDialog(false);
    submitTransaction();
  };

  const submitTransaction = async () => {
    setLoading(true);
    try {
      const data = {
        transaction_type: formik.values.transactionType,
        customer: formik.values.customerId ? 
          { id: formik.values.customerId } : 
          {
            document_type: formik.values.documentType,
            document_number: formik.values.documentNumber,
            full_name: formik.values.customerName,
            phone: formik.values.phone,
            email: formik.values.email,
          },
        currency_from: formik.values.currencyFrom,
        currency_to: 'BOB',
        amount_from: formik.values.amountFrom,
        exchange_rate: formik.values.exchangeRate,
        amount_to: calculateTotal(),
        payment_method: formik.values.paymentMethod,
        payment_reference: formik.values.paymentReference,
        notes: formik.values.notes,
      };

      await api.post('/transactions/', data);
      
      enqueueSnackbar('Transacción registrada exitosamente', { variant: 'success' });
      formik.resetForm();
      onSuccess();
      onClose();
    } catch (error: any) {
      enqueueSnackbar(
        error.response?.data?.error || 'Error al registrar transacción',
        { variant: 'error' }
      );
    } finally {
      setLoading(false);
    }
  };

  const calculateTotal = () => {
    const amount = parseFloat(formik.values.amountFrom as string) || 0;
    const rate = parseFloat(formik.values.exchangeRate as string) || 0;
    return amount * rate;
  };

const handleNext = async () => {
  const fieldsToValidate =
    activeStep === 0 ? ['customerName', 'documentNumber'] :
    activeStep === 1 ? ['currencyFrom', 'amountFrom', 'exchangeRate', 'paymentMethod'] :
    [];

  // Tocar todos los campos del paso actual para mostrar errores
  fieldsToValidate.forEach((field) => {
    formik.setFieldTouched(field, true, false);
  });

  // Validar cada campo usando formik directamente
  const errorResults = await Promise.all(
    fieldsToValidate.map((field) => formik.validateField(field))
  );

  // Revisar si algún campo tiene error
  const currentErrors = formik.errors as Record<string, string>;
  const hasErrors = fieldsToValidate.some((field) => !!currentErrors[field]);

  if (!hasErrors) {
    setActiveStep((prev) => prev + 1);
  }
};

  const handleBack = () => {
    setActiveStep((prev) => prev - 1);
  };

  const getStepContent = (step: number) => {
    switch (step) {
      case 0:
        return (
          <Grid container spacing={3}>
            <Grid xs={12}>
              <Autocomplete
                options={customers}
                getOptionLabel={(option) => 
                  `${option.full_name} - ${option.document_number}`
                }
                value={customers.find((c) => c.id === formik.values.customerId) || null}
                onChange={(_, value) => {
                  if (value) {
                    formik.setValues({
                      ...formik.values,
                      customerId: value.id,
                      customerName: value.full_name,
                      documentType: value.document_type,
                      documentNumber: value.document_number,
                      phone: value.phone || '',
                      email: value.email || '',
                    });
                  }
                }}
                renderInput={(params) => (
                  <TextField
                    {...params}
                    label="Buscar cliente existente"
                    variant="outlined"
                    fullWidth
                  />
                )}
              />
            </Grid>

            <Grid xs={12}>
              <Divider>O registrar nuevo cliente</Divider>
            </Grid>

            <Grid xs={4}>
              <FormControl fullWidth>
                <InputLabel>Tipo Doc.</InputLabel>
                <Select
                  value={formik.values.documentType}
                  onChange={formik.handleChange}
                  name="documentType"
                  disabled={!!formik.values.customerId}
                >
                  <MenuItem value="CI">CI</MenuItem>
                  <MenuItem value="NIT">NIT</MenuItem>
                  <MenuItem value="PASSPORT">Pasaporte</MenuItem>
                </Select>
              </FormControl>
            </Grid>

            <Grid xs={8}>
              <TextField
                fullWidth
                label="Número de Documento"
                name="documentNumber"
                value={formik.values.documentNumber}
                onChange={(e) => {
                  formik.handleChange(e);
                  searchCustomerByDocument(e.target.value);
                }}
                error={formik.touched.documentNumber && Boolean(formik.errors.documentNumber)}
                helperText={formik.touched.documentNumber && formik.errors.documentNumber}
                disabled={!!formik.values.customerId}
              />
            </Grid>

            <Grid xs={12}>
              <TextField
                fullWidth
                label="Nombre Completo"
                name="customerName"
                value={formik.values.customerName}
                onChange={formik.handleChange}
                error={formik.touched.customerName && Boolean(formik.errors.customerName)}
                helperText={formik.touched.customerName && formik.errors.customerName}
                disabled={!!formik.values.customerId}
              />
            </Grid>

            <Grid xs={12} sm={6}>
              <TextField
                fullWidth
                label="Teléfono (Opcional)"
                name="phone"
                value={formik.values.phone}
                onChange={formik.handleChange}
                disabled={!!formik.values.customerId}
              />
            </Grid>

            <Grid xs={12} sm={6}>
              <TextField
                fullWidth
                label="Email (Opcional)"
                name="email"
                type="email"
                value={formik.values.email}
                onChange={formik.handleChange}
                disabled={!!formik.values.customerId}
              />
            </Grid>
          </Grid>
        );

      case 1:
        return (
          <Grid container spacing={3}>
            <Grid xs={12}>
              <ToggleButtonGroup
                value={formik.values.transactionType}
                exclusive
                onChange={(_, value) => {
                  if (value) formik.setFieldValue('transactionType', value);
                }}
                fullWidth
              >
                <ToggleButton value="SELL" color="primary">
                  <SwapHoriz sx={{ mr: 1 }} />
                  Cliente Compra Divisas
                </ToggleButton>
                <ToggleButton value="BUY" color="secondary">
                  <SwapHoriz sx={{ mr: 1 }} />
                  Cliente Vende Divisas
                </ToggleButton>
              </ToggleButtonGroup>
            </Grid>

            <Grid xs={12} sm={4}>
              <FormControl fullWidth>
                <InputLabel>Divisa</InputLabel>
                <Select
                  value={formik.values.currencyFrom}
                  onChange={formik.handleChange}
                  name="currencyFrom"
                  error={formik.touched.currencyFrom && Boolean(formik.errors.currencyFrom)}
                >
                  <MenuItem value="USD">USD - Dólar</MenuItem>
                  <MenuItem value="EUR">EUR - Euro</MenuItem>
                  <MenuItem value="BRL">BRL - Real</MenuItem>
                  <MenuItem value="ARS">ARS - Peso Argentino</MenuItem>
                </Select>
              </FormControl>
            </Grid>

            <Grid xs={12} sm={4}>
              <NumericFormat
                customInput={TextField}
                fullWidth
                label="Monto"
                name="amountFrom"
                value={formik.values.amountFrom}
                onValueChange={(values) => {
                  formik.setFieldValue('amountFrom', values.floatValue);
                }}
                thousandSeparator=","
                decimalSeparator="."
                decimalScale={2}
                fixedDecimalScale
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      {formik.values.currencyFrom}
                    </InputAdornment>
                  ),
                }}
                error={formik.touched.amountFrom && Boolean(formik.errors.amountFrom)}
                helperText={formik.touched.amountFrom && formik.errors.amountFrom}
              />
            </Grid>

            <Grid xs={12} sm={4}>
              <NumericFormat
                customInput={TextField}
                fullWidth
                label="Tipo de Cambio"
                name="exchangeRate"
                value={formik.values.exchangeRate}
                onValueChange={(values) => {
                  formik.setFieldValue('exchangeRate', values.floatValue);
                }}
                thousandSeparator=","
                decimalSeparator="."
                decimalScale={4}
                fixedDecimalScale
                error={formik.touched.exchangeRate && Boolean(formik.errors.exchangeRate)}
                helperText={formik.touched.exchangeRate && formik.errors.exchangeRate}
              />
            </Grid>

            <Grid xs={12}>
              <Paper elevation={0} sx={{ p: 2, bgcolor: 'primary.light', color: 'primary.contrastText' }}>
                <Typography variant="h5" align="center">
                  Total en Bolivianos: {formatCurrency(calculateTotal())}
                </Typography>
              </Paper>
            </Grid>

            <Grid xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel>Método de Pago</InputLabel>
                <Select
                  value={formik.values.paymentMethod}
                  onChange={formik.handleChange}
                  name="paymentMethod"
                  error={formik.touched.paymentMethod && Boolean(formik.errors.paymentMethod)}
                >
                  <MenuItem value="CASH">Efectivo</MenuItem>
                  <MenuItem value="TRANSFER">Transferencia</MenuItem>
                  <MenuItem value="CHECK">Cheque</MenuItem>
                  <MenuItem value="CARD">Tarjeta</MenuItem>
                  <MenuItem value="QR">QR</MenuItem>
                </Select>
              </FormControl>
            </Grid>

            <Grid xs={12} sm={6}>
              <TextField
                fullWidth
                label="Referencia de Pago (Opcional)"
                name="paymentReference"
                value={formik.values.paymentReference}
                onChange={formik.handleChange}
              />
            </Grid>

            <Grid xs={12}>
              <TextField
                fullWidth
                multiline
                rows={2}
                label="Notas (Opcional)"
                name="notes"
                value={formik.values.notes}
                onChange={formik.handleChange}
              />
            </Grid>
          </Grid>
        );

      case 2:
        return (
          <Box>
            <Alert severity="info" sx={{ mb: 3 }}>
              Por favor, revise los detalles de la transacción antes de confirmar.
            </Alert>

            <Grid container spacing={2}>
              <Grid xs={12} sm={6}>
                <Typography variant="subtitle2" color="text.secondary">
                  Tipo de Transacción
                </Typography>
                <Typography variant="h6">
                  {formik.values.transactionType === 'SELL' ? 
                    'Cliente Compra Divisas' : 'Cliente Vende Divisas'}
                </Typography>
              </Grid>

              <Grid xs={12} sm={6}>
                <Typography variant="subtitle2" color="text.secondary">
                  Cliente
                </Typography>
                <Typography variant="h6">
                  {formik.values.customerName}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {formik.values.documentType} {formik.values.documentNumber}
                </Typography>
              </Grid>

              <Grid xs={12}>
                <Divider sx={{ my: 2 }} />
              </Grid>

              <Grid xs={12} sm={4}>
                <Typography variant="subtitle2" color="text.secondary">
                  Divisa
                </Typography>
                <Typography variant="h6">
                  {formik.values.currencyFrom}
                </Typography>
              </Grid>

              <Grid xs={12} sm={4}>
                <Typography variant="subtitle2" color="text.secondary">
                  Monto
                </Typography>
                <Typography variant="h6">
                  {formik.values.currencyFrom} {formatNumber(formik.values.amountFrom)}
                </Typography>
              </Grid>

              <Grid xs={12} sm={4}>
                <Typography variant="subtitle2" color="text.secondary">
                  Tipo de Cambio
                </Typography>
                <Typography variant="h6">
                  {formatNumber(formik.values.exchangeRate, 4)}
                </Typography>
              </Grid>

              <Grid xs={12}>
                <Paper elevation={0} sx={{ p: 2, bgcolor: 'success.light', mt: 2 }}>
                  <Typography variant="h5" align="center" color="success.contrastText">
                    Total: {formatCurrency(calculateTotal())}
                  </Typography>
                </Paper>
              </Grid>

              <Grid xs={12} sm={6}>
                <Typography variant="subtitle2" color="text.secondary">
                  Método de Pago
                </Typography>
                <Typography variant="h6">
                  {formik.values.paymentMethod}
                </Typography>
              </Grid>

              {formik.values.paymentReference && (
                <Grid xs={12} sm={6}>
                  <Typography variant="subtitle2" color="text.secondary">
                    Referencia
                  </Typography>
                  <Typography variant="h6">
                    {formik.values.paymentReference}
                  </Typography>
                </Grid>
              )}

              {formik.values.notes && (
                <Grid xs={12}>
                  <Typography variant="subtitle2" color="text.secondary">
                    Notas
                  </Typography>
                  <Typography variant="body1">
                    {formik.values.notes}
                  </Typography>
                </Grid>
              )}
            </Grid>
          </Box>
        );

      default:
        return null;
    }
  };

  return (
    <>
      <Dialog
        open={open}
        onClose={onClose}
        maxWidth="md"
        fullWidth
        PaperProps={{
          sx: { minHeight: '60vh' }
       }}
     >
       <DialogTitle>
         <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
           <Receipt />
           Nueva Transacción
         </Box>
       </DialogTitle>
       
       <DialogContent>
         <Box sx={{ mt: 2 }}>
           <Stepper activeStep={activeStep} alternativeLabel>
             {steps.map((label) => (
               <Step key={label}>
                 <StepLabel>{label}</StepLabel>
               </Step>
             ))}
           </Stepper>

           <Box sx={{ mt: 4 }}>
             {getStepContent(activeStep)}
           </Box>
         </Box>
       </DialogContent>

       <DialogActions sx={{ px: 3, pb: 2 }}>
         <Button onClick={onClose}>Cancelar</Button>
         <Box sx={{ flex: '1 1 auto' }} />
         
         {activeStep > 0 && (
           <Button onClick={handleBack}>
             Atrás
           </Button>
         )}
         
         {activeStep < steps.length - 1 ? (
           <Button
             variant="contained"
             onClick={handleNext}
           >
             Siguiente
           </Button>
         ) : (
           <Button
             variant="contained"
             color="success"
             onClick={() => formik.submitForm()}
             disabled={loading}
             startIcon={<Receipt />}
           >
             Confirmar Transacción
           </Button>
         )}
       </DialogActions>
     </Dialog>

     <PinDialog
       open={showPinDialog}
       onClose={() => setShowPinDialog(false)}
       onSubmit={handlePinSubmit}
       title="Verificación de PIN"
       message="Ingrese su PIN para confirmar la transacción"
     />
   </>
 );
};

export default TransactionForm;