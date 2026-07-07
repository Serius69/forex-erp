/**
 * ExcelImport — Importación masiva de datos históricos desde Excel.
 * Soporta: Transacciones, Capital, Tasas de Cambio, Inventario.
 */
import React, { useState, useRef, useCallback } from 'react';
import {
  Box, Typography, Paper, Button, Alert, AlertTitle,
  LinearProgress, Chip, Grid, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Accordion,
  AccordionSummary, AccordionDetails, Divider, List,
  ListItem, ListItemIcon, ListItemText, Switch, FormControlLabel,
} from '@mui/material';
import {
  CloudUpload, CheckCircle, Error, Warning, ExpandMore,
  TableChart, Download, Info,
} from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';

interface ImportResult {
  dry_run: boolean;
  file_name: string;
  sheets_found: string[];
  imported: Record<string, number>;
  errors: Record<string, string[]>;
  warnings: string[];
  summary: {
    total_imported: number;
    total_errors: number;
    status: 'success' | 'partial' | 'failed';
  };
}

const SHEET_SPECS = [
  {
    name: 'Transacciones',
    icon: '💱',
    columns: [
      'Fecha (YYYY-MM-DD)',
      'Tipo (COMPRA o VENTA)',
      'Divisa (USD, EUR, etc.)',
      'Monto (número)',
      'Tasa (número)',
      'BOB equivalente (número, opcional)',
      'Nombre cliente',
      'CI/NIT del cliente',
      'Teléfono (opcional)',
      'Método de pago (CASH, QR, TRANSFER, CHECK, CARD)',
    ],
  },
  {
    name: 'Capital',
    icon: '💰',
    columns: [
      'Fecha (YYYY-MM-DD)',
      'Efectivo BOB (número)',
      'QR/Digital BOB (número)',
      'Pasivos BOB (número)',
      'Notas (texto, opcional)',
    ],
  },
  {
    name: 'Tasas',
    icon: '📊',
    columns: [
      'Fecha (YYYY-MM-DD)',
      'Divisa (USD, EUR, etc.)',
      'Tasa Compra BOB (número)',
      'Tasa Venta BOB (número)',
      'Tasa Oficial BCB (número, opcional)',
      'Mercado (parallel, bcb, digital, official)',
    ],
  },
  {
    name: 'Inventario',
    icon: '📦',
    columns: [
      'Divisa (USD, EUR, etc.)',
      'Stock Físico (número)',
      'Stock Digital (número, opcional)',
      'Costo Promedio WAC (número, opcional)',
    ],
  },
];

const StatusChip = ({ status }: { status: 'success' | 'partial' | 'failed' }) => {
  const map = {
    success: { label: 'Exitoso',  color: 'success' as const, icon: <CheckCircle fontSize="small" /> },
    partial: { label: 'Parcial',  color: 'warning' as const, icon: <Warning fontSize="small" /> },
    failed:  { label: 'Con errores', color: 'error' as const, icon: <Error fontSize="small" /> },
  };
  const s = map[status];
  return <Chip label={s.label} color={s.color} icon={s.icon} size="small" />;
};

const ExcelImport: React.FC = () => {
  const [file,       setFile]       = useState<File | null>(null);
  const [dryRun,     setDryRun]     = useState(true);
  const [loading,    setLoading]    = useState(false);
  const [result,     setResult]     = useState<ImportResult | null>(null);
  const [dragging,   setDragging]   = useState(false);
  const fileRef  = useRef<HTMLInputElement>(null);
  const { enqueueSnackbar } = useSnackbar();

  const handleFile = (f: File | null) => {
    if (!f) return;
    if (!f.name.match(/\.(xlsx|xls)$/i)) {
      enqueueSnackbar('Solo se aceptan archivos Excel (.xlsx o .xls)', { variant: 'error' });
      return;
    }
    setFile(f);
    setResult(null);
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    handleFile(f);
  }, []);

  const handleImport = async () => {
    if (!file) return;
    setLoading(true);
    try {
      const form = new FormData();
      form.append('file', file);

      const res = await api.post(
        `/import/excel/?dry_run=${dryRun}`,
        form,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      );
      setResult(res.data);

      const { summary } = res.data;
      if (summary.status === 'success') {
        enqueueSnackbar(
          `${dryRun ? 'Validación' : 'Importación'} exitosa: ${summary.total_imported} registros`,
          { variant: 'success' },
        );
      } else if (summary.total_imported > 0) {
        enqueueSnackbar(
          `Parcial: ${summary.total_imported} importados, ${summary.total_errors} errores`,
          { variant: 'warning' },
        );
      } else {
        enqueueSnackbar('Importación fallida — revisa los errores', { variant: 'error' });
      }
    } catch (e: any) {
      enqueueSnackbar(
        e.response?.data?.error || 'Error al importar',
        { variant: 'error' },
      );
    } finally {
      setLoading(false);
    }
  };

  const downloadTemplate = () => {
    // Build a simple CSV template hint
    const hint = `Para descargar la plantilla Excel, contacta al administrador del sistema.
Los archivos deben tener las hojas: Transacciones, Capital, Tasas, Inventario.`;
    alert(hint);
  };

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box>
          <Typography variant="h4" fontWeight={800}>Importar desde Excel</Typography>
          <Typography variant="body2" color="text.secondary">
            Carga datos históricos de transacciones, capital, tasas e inventario
          </Typography>
        </Box>
        <Button
          variant="outlined"
          startIcon={<Download />}
          onClick={downloadTemplate}
          size="small"
        >
          Ver formato
        </Button>
      </Box>

      <Grid container spacing={3}>
        {/* LEFT: Upload + controls */}
        <Grid item xs={12} md={7}>
          {/* Drop zone */}
          <Paper
            variant="outlined"
            onDragOver={e => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            sx={{
              p: 4,
              textAlign: 'center',
              border: `2px dashed`,
              borderColor: dragging ? 'primary.main' : file ? 'success.main' : 'divider',
              bgcolor: dragging ? 'action.hover' : file ? 'success.50' : 'background.default',
              cursor: 'pointer',
              mb: 2,
              transition: 'all 0.2s',
            }}
            onClick={() => fileRef.current?.click()}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx,.xls"
              style={{ display: 'none' }}
              onChange={e => handleFile(e.target.files?.[0] ?? null)}
            />
            <CloudUpload sx={{ fontSize: 56, color: file ? 'success.main' : 'action.disabled', mb: 1 }} />
            {file ? (
              <>
                <Typography variant="h6" fontWeight={700} color="success.main">
                  {file.name}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {(file.size / 1024).toFixed(1)} KB · Click para cambiar
                </Typography>
              </>
            ) : (
              <>
                <Typography variant="h6" color="text.secondary">
                  Arrastra tu archivo Excel aquí
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  o haz click para seleccionar — .xlsx o .xls
                </Typography>
              </>
            )}
          </Paper>

          {/* Options */}
          <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
            <FormControlLabel
              control={
                <Switch
                  checked={dryRun}
                  onChange={e => setDryRun(e.target.checked)}
                  color="warning"
                />
              }
              label={
                <Box>
                  <Typography variant="body2" fontWeight={600}>
                    Modo de prueba (Dry Run)
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {dryRun
                      ? 'Solo valida los datos, NO guarda nada. Recomendado para primera revisión.'
                      : 'GUARDARÁ los datos en la base de datos. Desactiva solo cuando hayas validado.'}
                  </Typography>
                </Box>
              }
            />
          </Paper>

          {!dryRun && (
            <Alert severity="warning" sx={{ mb: 2 }}>
              <AlertTitle>Modo producción activo</AlertTitle>
              Los datos serán guardados definitivamente. Asegúrate de haber validado primero con Dry Run.
            </Alert>
          )}

          {/* Import button */}
          <Button
            variant="contained"
            size="large"
            fullWidth
            disabled={!file || loading}
            onClick={handleImport}
            startIcon={loading ? undefined : <CloudUpload />}
            color={dryRun ? 'warning' : 'primary'}
            sx={{ py: 1.5, fontWeight: 700 }}
          >
            {loading ? (
              <Box display="flex" alignItems="center" gap={1}>
                <CircularProgressSmall />
                Procesando...
              </Box>
            ) : dryRun ? 'Validar (Dry Run)' : 'Importar datos'}
          </Button>

          {loading && <LinearProgress sx={{ mt: 1, borderRadius: 1 }} />}
        </Grid>

        {/* RIGHT: Format guide */}
        <Grid item xs={12} md={5}>
          <Typography variant="subtitle1" fontWeight={700} mb={1}>
            Formato del archivo
          </Typography>
          <Alert severity="info" sx={{ mb: 2 }}>
            El archivo Excel debe tener hojas con los nombres exactos indicados.
            La primera fila de cada hoja es el encabezado (se ignora).
          </Alert>

          {SHEET_SPECS.map(sheet => (
            <Accordion key={sheet.name} disableGutters variant="outlined">
              <AccordionSummary expandIcon={<ExpandMore />}>
                <Typography fontWeight={600}>
                  {sheet.icon} Hoja: {sheet.name}
                </Typography>
              </AccordionSummary>
              <AccordionDetails sx={{ p: 1 }}>
                <List dense disablePadding>
                  {sheet.columns.map((col, i) => (
                    <ListItem key={i} disableGutters sx={{ py: 0.25 }}>
                      <ListItemIcon sx={{ minWidth: 28 }}>
                        <Typography variant="caption" color="primary" fontWeight={700}>
                          {String.fromCharCode(65 + i)}
                        </Typography>
                      </ListItemIcon>
                      <ListItemText
                        primary={col}
                        primaryTypographyProps={{ variant: 'caption' }}
                      />
                    </ListItem>
                  ))}
                </List>
              </AccordionDetails>
            </Accordion>
          ))}
        </Grid>
      </Grid>

      {/* Result */}
      {result && (
        <Box mt={3}>
          <Divider sx={{ mb: 2 }} />
          <Box display="flex" alignItems="center" gap={1} mb={2}>
            <Typography variant="h6" fontWeight={700}>
              Resultado {result.dry_run ? '(Dry Run)' : '(Importación real)'}
            </Typography>
            <StatusChip status={result.summary.status} />
          </Box>

          {/* Summary */}
          <Grid container spacing={2} mb={2}>
            {[
              { label: 'Hojas encontradas', value: result.sheets_found.length, color: 'text.primary' },
              { label: 'Registros procesados', value: result.summary.total_imported, color: 'success.main' },
              { label: 'Errores', value: result.summary.total_errors, color: result.summary.total_errors > 0 ? 'error.main' : 'text.secondary' },
            ].map(s => (
              <Grid item xs={4} key={s.label}>
                <Paper variant="outlined" sx={{ p: 1.5, textAlign: 'center' }}>
                  <Typography variant="caption" color="text.secondary" display="block">{s.label}</Typography>
                  <Typography variant="h5" fontWeight={800} color={s.color}>{s.value}</Typography>
                </Paper>
              </Grid>
            ))}
          </Grid>

          {/* Per-sheet results */}
          {Object.keys(result.imported).length > 0 && (
            <TableContainer component={Paper} variant="outlined" sx={{ mb: 2 }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell><strong>Hoja</strong></TableCell>
                    <TableCell align="right"><strong>Importados</strong></TableCell>
                    <TableCell align="right"><strong>Errores</strong></TableCell>
                    <TableCell><strong>Estado</strong></TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {Object.entries(result.imported).map(([sheet, count]) => {
                    const errs = result.errors[sheet] || [];
                    return (
                      <TableRow key={sheet} hover>
                        <TableCell><Typography fontWeight={600}>{sheet}</Typography></TableCell>
                        <TableCell align="right">
                          <Typography color="success.main" fontWeight={700}>{count}</Typography>
                        </TableCell>
                        <TableCell align="right">
                          <Typography color={errs.length ? 'error.main' : 'text.secondary'}>
                            {errs.length}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          {errs.length === 0
                            ? <Chip label="OK" color="success" size="small" />
                            : <Chip label="Errores" color="error" size="small" />}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </TableContainer>
          )}

          {/* Errors */}
          {Object.keys(result.errors).length > 0 && (
            <Alert severity="error" sx={{ mb: 2 }}>
              <AlertTitle>Errores de importación</AlertTitle>
              {Object.entries(result.errors).map(([sheet, errs]) => (
                <Box key={sheet} mt={1}>
                  <Typography variant="body2" fontWeight={700}>{sheet}:</Typography>
                  {errs.map((e, i) => (
                    <Typography key={i} variant="caption" display="block" pl={2}>• {e}</Typography>
                  ))}
                </Box>
              ))}
            </Alert>
          )}

          {/* Warnings */}
          {result.warnings.length > 0 && (
            <Alert severity="warning">
              <AlertTitle>Advertencias</AlertTitle>
              {result.warnings.map((w, i) => (
                <Typography key={i} variant="caption" display="block">• {w}</Typography>
              ))}
            </Alert>
          )}

          {/* Next step hint */}
          {result.dry_run && result.summary.total_errors === 0 && (
            <Alert severity="success" sx={{ mt: 2 }}>
              <AlertTitle>Validación exitosa</AlertTitle>
              El archivo está correcto. Desactiva "Modo de prueba" y vuelve a importar para guardar los datos.
            </Alert>
          )}
        </Box>
      )}
    </Box>
  );
};

// Small inline spinner
const CircularProgressSmall = () => (
  <Box sx={{ width: 18, height: 18, border: '2px solid rgba(255,255,255,0.3)', borderTopColor: 'white',
    borderRadius: '50%', animation: 'spin 0.8s linear infinite',
    '@keyframes spin': { to: { transform: 'rotate(360deg)' } } }} />
);

export default ExcelImport;
