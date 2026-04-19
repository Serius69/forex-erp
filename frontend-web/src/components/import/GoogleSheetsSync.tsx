/**
 * GoogleSheetsSync
 *
 * Integración bidireccional con Google Sheets:
 *   IMPORTAR → Lee Capital, Inventario y Tasas desde el Sheet → guarda en DB
 *   EXPORTAR → Escribe snapshot del estado actual en pestaña 'Kapitalya_Snapshot'
 *
 * Flujo:
 *   1. Usuario pega URL del Google Sheet
 *   2. Se valida automáticamente (debounce 600 ms) → muestra hojas detectadas
 *   3. Selecciona targets + dry_run
 *   4. "Sincronizar" → POST /api/migration/quick_sync/
 *   5. "Exportar snapshot" → POST /api/migration/export_snapshot/
 */
import React, { useState, useCallback, useEffect, useRef } from 'react';
import {
  Box, Typography, Paper, Button, TextField, Alert, AlertTitle,
  Chip, Grid, CircularProgress, Divider, Switch, FormControlLabel,
  List, ListItem, ListItemText, ListItemIcon, Tooltip, Collapse,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  LinearProgress,
} from '@mui/material';
import {
  Google, Sync, CloudUpload, CheckCircle, Error as ErrorIcon,
  Warning, Info, Link, ExpandMore, ExpandLess, OpenInNew,
  CloudDownload, Inventory2, AccountBalance, ShowChart,
} from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';

// ── Types ─────────────────────────────────────────────────────────────────────

interface SheetMeta {
  spreadsheet_id:  string;
  title:           string;
  available_sheets: string[];
  detected_targets: Record<string, string>;   // {capital: 'Capital', rates: 'Tasas', ...}
  can_sync:        boolean;
  can_export:      boolean;
}

interface SyncResult {
  spreadsheet_id:  string;
  title:           string;
  sheets_synced:   string[];
  dry_run:         boolean;
  total_synced:    number;
  total_errors:    number;
  status:          'ok' | 'partial' | 'error';
  results:         Record<string, { synced: number; errors: string[]; dry_run: boolean }>;
}

interface ExportResult {
  spreadsheet_id:  string;
  sheet_tab:       string;
  rows_written:    number;
  snapshot_at:     string;
}

// ── Constants ────────────────────────────────────────────────────────────────

const TARGET_CONFIG: Record<string, { label: string; icon: React.ReactElement; color: string }> = {
  capital:      { label: 'Capital',    icon: <AccountBalance fontSize="small" />, color: '#1976d2' },
  inventory:    { label: 'Inventario', icon: <Inventory2 fontSize="small" />,    color: '#388e3c' },
  rates:        { label: 'Tasas',      icon: <ShowChart fontSize="small" />,      color: '#f57c00' },
};

// ── Sub-components ────────────────────────────────────────────────────────────

const TargetChip: React.FC<{
  target:   string;
  selected: boolean;
  sheet:    string | undefined;
  onClick:  () => void;
}> = ({ target, selected, sheet, onClick }) => {
  const cfg = TARGET_CONFIG[target] ?? { label: target, icon: <Info fontSize="small" />, color: '#757575' };
  return (
    <Chip
      icon={cfg.icon}
      label={`${cfg.label}${sheet ? ` (${sheet})` : ''}`}
      onClick={onClick}
      color={selected ? 'primary' : 'default'}
      variant={selected ? 'filled' : 'outlined'}
      sx={{
        borderColor: selected ? undefined : cfg.color,
        color:       selected ? undefined : cfg.color,
        fontWeight:  600,
        '& .MuiChip-icon': { color: selected ? 'inherit' : cfg.color },
      }}
    />
  );
};

const ResultRow: React.FC<{
  target:  string;
  result:  SyncResult['results'][string];
}> = ({ target, result }) => {
  const [open, setOpen] = useState(false);
  const cfg = TARGET_CONFIG[target] ?? { label: target };
  const hasErrors = result.errors.length > 0;
  return (
    <>
      <TableRow
        hover
        sx={{ cursor: hasErrors ? 'pointer' : 'default' }}
        onClick={() => hasErrors && setOpen(o => !o)}
      >
        <TableCell>
          <Box display="flex" alignItems="center" gap={1}>
            {TARGET_CONFIG[target]?.icon}
            <Typography fontWeight={600}>{cfg.label}</Typography>
          </Box>
        </TableCell>
        <TableCell align="right">
          <Typography color="success.main" fontWeight={700}>{result.synced}</Typography>
        </TableCell>
        <TableCell align="right">
          <Typography color={hasErrors ? 'error.main' : 'text.secondary'}>
            {result.errors.length}
          </Typography>
        </TableCell>
        <TableCell>
          {result.dry_run
            ? <Chip label="Dry Run" color="warning" size="small" />
            : hasErrors
              ? <Chip label="Parcial" color="warning" size="small" icon={<Warning />} />
              : <Chip label="OK" color="success" size="small" icon={<CheckCircle />} />}
        </TableCell>
        <TableCell sx={{ width: 32, p: 0.5 }}>
          {hasErrors && (open ? <ExpandLess fontSize="small" /> : <ExpandMore fontSize="small" />)}
        </TableCell>
      </TableRow>
      {hasErrors && (
        <TableRow>
          <TableCell colSpan={5} sx={{ pb: 0, pt: 0 }}>
            <Collapse in={open} timeout="auto" unmountOnExit>
              <Box p={1.5} bgcolor="error.50" borderRadius={1} mb={1}>
                {result.errors.slice(0, 10).map((err, i) => (
                  <Typography key={i} variant="caption" display="block" color="error.main">
                    • {err}
                  </Typography>
                ))}
                {result.errors.length > 10 && (
                  <Typography variant="caption" color="text.secondary">
                    … y {result.errors.length - 10} errores más
                  </Typography>
                )}
              </Box>
            </Collapse>
          </TableCell>
        </TableRow>
      )}
    </>
  );
};

// ── Main component ────────────────────────────────────────────────────────────

const GoogleSheetsSync: React.FC = () => {
  const [url,         setUrl]         = useState('');
  const [meta,        setMeta]        = useState<SheetMeta | null>(null);
  const [metaLoading, setMetaLoading] = useState(false);
  const [metaError,   setMetaError]   = useState('');
  const [targets,     setTargets]     = useState<Set<string>>(new Set(['capital', 'inventory', 'rates']));
  const [dryRun,      setDryRun]      = useState(false);
  const [syncing,     setSyncing]     = useState(false);
  const [syncResult,  setSyncResult]  = useState<SyncResult | null>(null);
  const [exporting,   setExporting]   = useState(false);
  const [exportResult,setExportResult]= useState<ExportResult | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { enqueueSnackbar } = useSnackbar();

  // ── Auto-validate URL ────────────────────────────────────────────────────

  const validateUrl = useCallback(async (rawUrl: string) => {
    if (!rawUrl.trim()) {
      setMeta(null);
      setMetaError('');
      return;
    }
    setMetaLoading(true);
    setMetaError('');
    setMeta(null);
    setSyncResult(null);
    setExportResult(null);
    try {
      const resp = await api.get('/migration/sheets_info/', {
        params: { sheet_url: rawUrl.trim() },
      });
      setMeta(resp.data);
      // Auto-select detected targets
      if (resp.data.detected_targets) {
        setTargets(new Set(Object.keys(resp.data.detected_targets)));
      }
    } catch (e: any) {
      const msg = e.response?.data?.error || 'No se pudo validar la URL';
      setMetaError(msg);
    } finally {
      setMetaLoading(false);
    }
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => validateUrl(url), 600);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [url, validateUrl]);

  // ── Toggle target ────────────────────────────────────────────────────────

  const toggleTarget = (t: string) => {
    setTargets(prev => {
      const next = new Set(prev);
      next.has(t) ? next.delete(t) : next.add(t);
      return next;
    });
  };

  // ── Quick sync ───────────────────────────────────────────────────────────

  const handleSync = async () => {
    if (!url.trim() || targets.size === 0) return;
    setSyncing(true);
    setSyncResult(null);
    setExportResult(null);
    try {
      const resp = await api.post('/migration/quick_sync/', {
        sheet_url: url.trim(),
        targets:   Array.from(targets),
        dry_run:   dryRun,
      });
      setSyncResult(resp.data);

      const { total_synced, total_errors, dry_run } = resp.data;
      if (total_errors === 0) {
        enqueueSnackbar(
          `${dry_run ? 'Validación' : 'Sincronización'} exitosa — ${total_synced} registros`,
          { variant: 'success' },
        );
      } else {
        enqueueSnackbar(
          `Sincronización parcial — ${total_synced} OK, ${total_errors} errores`,
          { variant: 'warning' },
        );
      }
    } catch (e: any) {
      const msg = e.response?.data?.error || 'Error al sincronizar';
      enqueueSnackbar(msg, { variant: 'error' });
    } finally {
      setSyncing(false);
    }
  };

  // ── Export snapshot ──────────────────────────────────────────────────────

  const handleExport = async () => {
    if (!url.trim()) return;
    setExporting(true);
    setExportResult(null);
    try {
      const resp = await api.post('/migration/export_snapshot/', { sheet_url: url.trim() });
      setExportResult(resp.data);
      enqueueSnackbar(
        `Snapshot exportado — ${resp.data.rows_written} filas en "${resp.data.sheet_tab}"`,
        { variant: 'success' },
      );
    } catch (e: any) {
      const msg = e.response?.data?.error || 'Error al exportar snapshot';
      enqueueSnackbar(msg, { variant: 'error' });
    } finally {
      setExporting(false);
    }
  };

  // ── Helpers ──────────────────────────────────────────────────────────────

  const canSync   = !!meta?.can_sync && targets.size > 0 && !syncing;
  const canExport = !!meta && !exporting && url.trim().length > 0;

  const sheetLink = meta
    ? `https://docs.google.com/spreadsheets/d/${meta.spreadsheet_id}/edit`
    : null;

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <Box>
      {/* Header */}
      <Box display="flex" justifyContent="space-between" alignItems="flex-start" mb={3}>
        <Box>
          <Box display="flex" alignItems="center" gap={1} mb={0.5}>
            <Google color="error" />
            <Typography variant="h4" fontWeight={800}>Google Sheets</Typography>
          </Box>
          <Typography variant="body2" color="text.secondary">
            Importa Capital, Inventario y Tasas desde tu Sheet — o exporta un snapshot del sistema.
          </Typography>
        </Box>
        {sheetLink && (
          <Tooltip title="Abrir spreadsheet">
            <Button
              size="small"
              variant="outlined"
              startIcon={<OpenInNew />}
              href={sheetLink}
              target="_blank"
              rel="noopener noreferrer"
            >
              Abrir Sheet
            </Button>
          </Tooltip>
        )}
      </Box>

      <Grid container spacing={3}>
        {/* LEFT: URL + controls */}
        <Grid item xs={12} md={7}>

          {/* URL input */}
          <Paper variant="outlined" sx={{ p: 2.5, mb: 2 }}>
            <Typography variant="subtitle2" fontWeight={700} mb={1.5}>
              Link del Google Sheet
            </Typography>
            <TextField
              fullWidth
              size="small"
              placeholder="https://docs.google.com/spreadsheets/d/..."
              value={url}
              onChange={e => setUrl(e.target.value)}
              InputProps={{
                startAdornment: (
                  <Link fontSize="small" sx={{ mr: 1, color: 'text.secondary', flexShrink: 0 }} />
                ),
                endAdornment: metaLoading
                  ? <CircularProgress size={18} sx={{ flexShrink: 0 }} />
                  : meta
                    ? <CheckCircle fontSize="small" color="success" sx={{ flexShrink: 0 }} />
                    : null,
              }}
              error={!!metaError}
              helperText={metaError || (meta ? `"${meta.title}"` : 'Pega la URL completa del spreadsheet')}
            />
          </Paper>

          {/* Detected sheets */}
          {meta && (
            <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
              <Typography variant="subtitle2" fontWeight={700} mb={1.5}>
                Hojas detectadas — selecciona qué importar
              </Typography>
              {Object.keys(TARGET_CONFIG).length > 0 && (
                <Box display="flex" gap={1} flexWrap="wrap">
                  {Object.keys(TARGET_CONFIG).map(t => (
                    <TargetChip
                      key={t}
                      target={t}
                      selected={targets.has(t)}
                      sheet={meta.detected_targets[t]}
                      onClick={() => toggleTarget(t)}
                    />
                  ))}
                </Box>
              )}
              {!meta.can_sync && (
                <Alert severity="warning" sx={{ mt: 1.5 }}>
                  No se detectaron hojas reconocidas (Capital, Inventario, Tasas).
                  Revisa que los nombres de las pestañas coincidan.
                </Alert>
              )}
            </Paper>
          )}

          {/* Options */}
          {meta && (
            <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
              <FormControlLabel
                control={
                  <Switch
                    checked={dryRun}
                    onChange={e => setDryRun(e.target.checked)}
                    color="warning"
                    size="small"
                  />
                }
                label={
                  <Box>
                    <Typography variant="body2" fontWeight={600}>
                      Modo prueba (Dry Run)
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {dryRun
                        ? 'Solo valida la estructura — no guarda datos.'
                        : 'Guardará los datos en la base de datos.'}
                    </Typography>
                  </Box>
                }
              />
            </Paper>
          )}

          {!dryRun && meta?.can_sync && (
            <Alert severity="info" sx={{ mb: 2 }} icon={<Info />}>
              Los registros existentes con la misma fecha/divisa serán <strong>actualizados</strong>,
              los nuevos serán creados.
            </Alert>
          )}

          {/* Action buttons */}
          <Box display="flex" gap={1.5} flexWrap="wrap">
            <Button
              variant="contained"
              size="large"
              disabled={!canSync}
              onClick={handleSync}
              startIcon={syncing ? undefined : <Sync />}
              color={dryRun ? 'warning' : 'primary'}
              sx={{ flex: 1, minWidth: 160, fontWeight: 700, py: 1.25 }}
            >
              {syncing
                ? <Box display="flex" alignItems="center" gap={1}>
                    <CircularProgress size={18} color="inherit" />
                    Sincronizando...
                  </Box>
                : dryRun ? 'Validar' : 'Sincronizar'}
            </Button>

            <Tooltip
              title={
                !canExport
                  ? 'Pega una URL válida primero'
                  : 'Requiere GOOGLE_SHEETS_WRITABLE=True en el servidor'
              }
            >
              <span>
                <Button
                  variant="outlined"
                  size="large"
                  disabled={!canExport}
                  onClick={handleExport}
                  startIcon={exporting ? undefined : <CloudUpload />}
                  sx={{ flex: 1, minWidth: 160, fontWeight: 700, py: 1.25 }}
                >
                  {exporting
                    ? <Box display="flex" alignItems="center" gap={1}>
                        <CircularProgress size={18} color="inherit" />
                        Exportando...
                      </Box>
                    : 'Exportar snapshot'}
                </Button>
              </span>
            </Tooltip>
          </Box>

          {(syncing || exporting) && <LinearProgress sx={{ mt: 1.5, borderRadius: 1 }} />}
        </Grid>

        {/* RIGHT: Format guide */}
        <Grid item xs={12} md={5}>
          <Paper variant="outlined" sx={{ p: 2 }}>
            <Typography variant="subtitle2" fontWeight={700} mb={1.5}>
              Formato esperado de las hojas
            </Typography>
            <Alert severity="info" sx={{ mb: 1.5 }} icon={<Info />}>
              La primera fila de cada pestaña es el encabezado (se ignora al importar).
              Los nombres de las pestañas son flexibles.
            </Alert>

            {[
              {
                target: 'capital',
                tab:    'Capital',
                cols:   ['Fecha', 'Efectivo BOB', 'QR/Digital BOB', 'Pasivos BOB', 'Notas (opcional)'],
              },
              {
                target: 'inventory',
                tab:    'Inventario',
                cols:   ['Divisa (USD, EUR…)', 'Stock Físico', 'Stock Digital (opcional)', 'WAC (opcional)'],
              },
              {
                target: 'rates',
                tab:    'Tasas',
                cols:   ['Fecha', 'Divisa', 'Tasa Compra BOB', 'Tasa Venta BOB', 'Tasa BCB (opcional)', 'Mercado (opcional)'],
              },
            ].map(({ target, tab, cols }) => {
              const cfg = TARGET_CONFIG[target];
              return (
                <Box key={target} mb={1.5}>
                  <Box display="flex" alignItems="center" gap={0.75} mb={0.75}>
                    {cfg.icon}
                    <Typography variant="body2" fontWeight={700} color={cfg.color}>
                      Pestaña: {tab}
                    </Typography>
                  </Box>
                  <List dense disablePadding>
                    {cols.map((col, i) => (
                      <ListItem key={i} disableGutters sx={{ py: 0.15 }}>
                        <ListItemIcon sx={{ minWidth: 24 }}>
                          <Typography variant="caption" color={cfg.color} fontWeight={700}>
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
                </Box>
              );
            })}

            <Divider sx={{ my: 1.5 }} />
            <Typography variant="caption" color="text.secondary">
              Pestañas reconocidas automáticamente: Capital, Inventario, Tasas
              (y variantes como CAPITAL, Tipos de Cambio, Stock, etc.)
            </Typography>
          </Paper>
        </Grid>
      </Grid>

      {/* ── Sync results ── */}
      {syncResult && (
        <Box mt={3}>
          <Divider sx={{ mb: 2 }} />
          <Box display="flex" alignItems="center" gap={1.5} mb={2}>
            <Typography variant="h6" fontWeight={700}>
              Resultado {syncResult.dry_run ? '(Dry Run — no se guardó nada)' : '(datos guardados)'}
            </Typography>
            <Chip
              label={syncResult.total_errors === 0 ? 'Exitoso' : 'Parcial'}
              color={syncResult.total_errors === 0 ? 'success' : 'warning'}
              size="small"
            />
          </Box>

          {/* Summary stats */}
          <Grid container spacing={2} mb={2}>
            {[
              { label: 'Hojas sincronizadas', value: syncResult.sheets_synced.length, color: 'text.primary' },
              { label: 'Registros procesados', value: syncResult.total_synced, color: 'success.main' },
              { label: 'Errores', value: syncResult.total_errors, color: syncResult.total_errors > 0 ? 'error.main' : 'text.secondary' },
            ].map(s => (
              <Grid item xs={4} key={s.label}>
                <Paper variant="outlined" sx={{ p: 1.5, textAlign: 'center' }}>
                  <Typography variant="caption" color="text.secondary" display="block">{s.label}</Typography>
                  <Typography variant="h5" fontWeight={800} color={s.color}>{s.value}</Typography>
                </Paper>
              </Grid>
            ))}
          </Grid>

          {/* Per-target table */}
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow sx={{ bgcolor: 'action.hover' }}>
                  <TableCell><strong>Módulo</strong></TableCell>
                  <TableCell align="right"><strong>Procesados</strong></TableCell>
                  <TableCell align="right"><strong>Errores</strong></TableCell>
                  <TableCell><strong>Estado</strong></TableCell>
                  <TableCell sx={{ width: 32 }} />
                </TableRow>
              </TableHead>
              <TableBody>
                {Object.entries(syncResult.results).map(([target, result]) => (
                  <ResultRow key={target} target={target} result={result} />
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          {/* Next step hint */}
          {syncResult.dry_run && syncResult.total_errors === 0 && (
            <Alert severity="success" sx={{ mt: 2 }}>
              <AlertTitle>Validación exitosa</AlertTitle>
              Los datos tienen la estructura correcta.
              Desactiva "Modo prueba" y vuelve a sincronizar para guardar.
            </Alert>
          )}
        </Box>
      )}

      {/* ── Export result ── */}
      {exportResult && (
        <Box mt={3}>
          <Divider sx={{ mb: 2 }} />
          <Alert severity="success" icon={<CloudDownload />}>
            <AlertTitle>Snapshot exportado correctamente</AlertTitle>
            <Typography variant="body2">
              Se escribieron <strong>{exportResult.rows_written} filas</strong> en la
              pestaña <strong>"{exportResult.sheet_tab}"</strong> del spreadsheet.
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" mt={0.5}>
              Generado: {new Date(exportResult.snapshot_at).toLocaleString('es-BO')}
            </Typography>
            {sheetLink && (
              <Button
                size="small"
                startIcon={<OpenInNew />}
                href={sheetLink}
                target="_blank"
                rel="noopener noreferrer"
                sx={{ mt: 1 }}
              >
                Ver en Google Sheets
              </Button>
            )}
          </Alert>
        </Box>
      )}
    </Box>
  );
};

export default GoogleSheetsSync;
