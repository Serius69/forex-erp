/**
 * AlertasPage — Página completa de gestión de alertas del sistema Kapitalya.
 *
 * Módulo 7: Alertas Inteligentes
 * - Bajo stock tarjetas
 * - TC fuera de rango
 * - Caída de margen
 * - Oportunidades de compra/venta
 *
 * Tipo: visual (badges) + listado paginado
 */
import React, { useState, useCallback } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Chip, Button,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Paper, Tabs, Tab, Alert, IconButton, Tooltip, Divider,
  CircularProgress, Badge, Dialog, DialogTitle, DialogContent,
  DialogActions, LinearProgress, TablePagination,
} from '@mui/material';
import {
  Warning, Error as ErrorIcon, Info, CheckCircle,
  DoneAll, Refresh, Notifications, NotificationsOff,
  Inventory2, CurrencyExchange, TrendingDown, FlashOn,
  Visibility, Close,
} from '@mui/icons-material';
import { formatDistanceToNow, format } from 'date-fns';
import { es } from 'date-fns/locale';
import { useAlerts, AlertLogEntry, AlertSeverity, AlertSource } from '../../hooks/useAlerts';

// ── Config ────────────────────────────────────────────────────────────────────

const SEV_CONFIG: Record<AlertSeverity, {
  label: string;
  color: 'error' | 'warning' | 'info' | 'default';
  chipColor: 'error' | 'warning' | 'info' | 'default';
  icon: React.ReactElement;
  bg: string;
}> = {
  CRITICAL: { label: 'Crítica',  color: 'error',   chipColor: 'error',   icon: <ErrorIcon />,  bg: '#fff5f5' },
  HIGH:     { label: 'Alta',     color: 'warning',  chipColor: 'warning', icon: <Warning />,    bg: '#fffbea' },
  MEDIUM:   { label: 'Media',    color: 'info',     chipColor: 'info',    icon: <Info />,       bg: '#f0f7ff' },
  LOW:      { label: 'Baja',     color: 'default',  chipColor: 'default', icon: <Info />,       bg: '#fafafa' },
};

const SOURCE_ICON: Record<AlertSource, React.ReactElement> = {
  SNAPSHOT:    <CheckCircle fontSize="small" />,
  TRANSACTION: <FlashOn fontSize="small" />,
  ANOMALY:     <Warning fontSize="small" />,
  SYSTEM:      <ErrorIcon fontSize="small" />,
  INVENTORY:   <Inventory2 fontSize="small" />,
  RATES:       <CurrencyExchange fontSize="small" />,
  // AlertGenerator categories (migration 0002)
  PRECIO:      <TrendingDown fontSize="small" />,
  RIESGO:      <Warning fontSize="small" />,
  OPERATIVO:   <Info fontSize="small" />,
  OPORTUNIDAD: <FlashOn fontSize="small" />,
};

const SOURCE_LABEL: Record<AlertSource, string> = {
  SNAPSHOT:    'Snapshot',
  TRANSACTION: 'Transacción',
  ANOMALY:     'Anomalía',
  SYSTEM:      'Sistema',
  INVENTORY:   'Inventario',
  RATES:       'Tasas',
  PRECIO:      'Precio',
  RIESGO:      'Riesgo',
  OPERATIVO:   'Operativo',
  OPORTUNIDAD: 'Oportunidad',
};

const TABS = ['Todas', 'Críticas', 'Altas', 'Medias', 'Bajas'];
const SEV_BY_TAB: (AlertSeverity | null)[] = [null, 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];

// ── KPI Summary Card ──────────────────────────────────────────────────────────

const SummaryCard = ({
  label, count, color, icon, active,
}: {
  label: string; count: number; color: string;
  icon: React.ReactElement; active: boolean;
}) => (
  <Card sx={{
    borderTop: `3px solid ${active ? color : 'transparent'}`,
    cursor: 'pointer',
    transition: 'box-shadow 0.2s',
    '&:hover': { boxShadow: 4 },
  }}>
    <CardContent sx={{ py: 1.5 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center">
        <Box>
          <Typography variant="caption" color="text.secondary" fontWeight={600} textTransform="uppercase" letterSpacing={0.5}>
            {label}
          </Typography>
          <Typography variant="h4" fontWeight={800} sx={{ color, lineHeight: 1.1, mt: 0.25 }}>
            {count}
          </Typography>
        </Box>
        <Box sx={{ color, opacity: 0.7 }}>{icon}</Box>
      </Box>
    </CardContent>
  </Card>
);

// ── Alert Row ─────────────────────────────────────────────────────────────────

const AlertRow: React.FC<{
  alert: AlertLogEntry;
  onAck: (id: string) => void;
  onView: (a: AlertLogEntry) => void;
}> = ({ alert, onAck, onView }) => {
  const sev  = SEV_CONFIG[alert.severity] ?? SEV_CONFIG.LOW;
  const time = (() => {
    try { return formatDistanceToNow(new Date(alert.created_at), { addSuffix: true, locale: es }); }
    catch { return alert.created_at; }
  })();

  return (
    <TableRow
      hover
      sx={{
        opacity: alert.is_acknowledged ? 0.55 : 1,
        bgcolor: alert.is_acknowledged ? 'transparent' : sev.bg,
      }}
    >
      <TableCell sx={{ width: 8, p: 0 }}>
        {!alert.is_acknowledged && (
          <Box sx={{ width: 4, height: '100%', bgcolor: `${sev.color}.main`, minHeight: 48 }} />
        )}
      </TableCell>
      <TableCell>
        <Chip
          icon={sev.icon}
          label={sev.label}
          size="small"
          color={sev.chipColor}
          variant={alert.is_acknowledged ? 'outlined' : 'filled'}
        />
      </TableCell>
      <TableCell>
        <Box display="flex" alignItems="center" gap={0.75}>
          <Box sx={{ color: 'text.secondary', display: 'flex' }}>
            {SOURCE_ICON[alert.source]}
          </Box>
          <Chip label={SOURCE_LABEL[alert.source]} size="small" variant="outlined" />
        </Box>
      </TableCell>
      <TableCell>
        <Typography variant="body2" fontWeight={alert.is_acknowledged ? 400 : 600}>
          {alert.title}
        </Typography>
        <Typography variant="caption" color="text.secondary" noWrap sx={{ maxWidth: 320, display: 'block' }}>
          {alert.message}
        </Typography>
      </TableCell>
      <TableCell>
        <Typography variant="caption" color="text.secondary">{time}</Typography>
      </TableCell>
      <TableCell align="right">
        <Box display="flex" gap={0.5} justifyContent="flex-end">
          <Tooltip title="Ver detalle">
            <IconButton size="small" onClick={() => onView(alert)}>
              <Visibility fontSize="small" />
            </IconButton>
          </Tooltip>
          {!alert.is_acknowledged && (
            <Tooltip title="Reconocer">
              <IconButton size="small" color="success" onClick={() => onAck(alert.id)}>
                <CheckCircle fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
        </Box>
      </TableCell>
    </TableRow>
  );
};

// ── Detail Dialog ─────────────────────────────────────────────────────────────

const DetailDialog: React.FC<{
  alert: AlertLogEntry | null;
  onClose: () => void;
  onAck: (id: string) => void;
}> = ({ alert, onClose, onAck }) => {
  if (!alert) return null;
  const sev = SEV_CONFIG[alert.severity] ?? SEV_CONFIG.LOW;

  return (
    <Dialog open maxWidth="sm" fullWidth onClose={onClose}>
      <DialogTitle>
        <Box display="flex" alignItems="center" gap={1.5}>
          <Chip icon={sev.icon} label={sev.label} color={sev.chipColor} size="small" />
          <Typography variant="h6" fontWeight={700}>{alert.title}</Typography>
          <Box flex={1} />
          <IconButton size="small" onClick={onClose}><Close /></IconButton>
        </Box>
      </DialogTitle>
      <DialogContent dividers>
        <Typography variant="body1" mb={2}>{alert.message}</Typography>
        <Divider sx={{ my: 1.5 }} />
        <Grid container spacing={1}>
          {[
            { label: 'Fuente',    value: SOURCE_LABEL[alert.source] },
            { label: 'Severidad', value: sev.label },
            { label: 'Fecha',     value: (() => { try { return format(new Date(alert.created_at), 'dd/MM/yyyy HH:mm:ss', { locale: es }); } catch { return alert.created_at; } })() },
            { label: 'Estado',    value: alert.is_acknowledged ? `Reconocida por ${alert.acknowledged_by_name}` : 'Pendiente' },
            ...(alert.branch_name ? [{ label: 'Sucursal', value: alert.branch_name }] : []),
            ...(alert.triggered_by_name ? [{ label: 'Disparada por', value: alert.triggered_by_name }] : []),
          ].map(({ label, value }) => (
            <Grid item xs={6} key={label}>
              <Typography variant="caption" color="text.secondary" fontWeight={600} textTransform="uppercase">{label}</Typography>
              <Typography variant="body2" fontWeight={600}>{value}</Typography>
            </Grid>
          ))}
        </Grid>
        {Object.keys(alert.data ?? {}).length > 0 && (
          <Box mt={2}>
            <Typography variant="caption" color="text.secondary" fontWeight={600} textTransform="uppercase">Datos adicionales</Typography>
            <Paper variant="outlined" sx={{ p: 1.5, mt: 0.5, fontFamily: 'monospace', fontSize: '0.75rem', bgcolor: '#f9f9f9', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
              {JSON.stringify(alert.data, null, 2)}
            </Paper>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cerrar</Button>
        {!alert.is_acknowledged && (
          <Button
            variant="contained"
            color="success"
            startIcon={<CheckCircle />}
            onClick={() => { onAck(alert.id); onClose(); }}
          >
            Reconocer
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
};

// ── Main Page ─────────────────────────────────────────────────────────────────

const AlertasPage: React.FC = () => {
  const { alerts, summary, loading, refresh, acknowledge, acknowledgeAll } = useAlerts();
  const [tab,        setTab]        = useState(0);
  const [selected,   setSelected]   = useState<AlertLogEntry | null>(null);
  const [acking,     setAcking]     = useState(false);

  const filteredSev = SEV_BY_TAB[tab];
  const visible = filteredSev
    ? alerts.filter(a => a.severity === filteredSev)
    : alerts;

  const unreadByTab = SEV_BY_TAB.map(sev =>
    sev ? (summary?.by_severity[sev] ?? 0) : (summary?.total_active ?? 0)
  );

  const handleAck = useCallback(async (id: string) => {
    await acknowledge(id);
  }, [acknowledge]);

  const handleAckAll = useCallback(async () => {
    setAcking(true);
    try { await acknowledgeAll(); }
    finally { setAcking(false); }
  }, [acknowledgeAll]);

  return (
    <Box p={3}>
      {/* ── Header ── */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box>
          <Typography variant="h4" fontWeight={700}>
            <Notifications sx={{ mr: 1, verticalAlign: 'middle', color: 'warning.main' }} />
            Alertas del Sistema
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Monitoreo en tiempo real · {summary?.total_active ?? 0} alertas activas
          </Typography>
        </Box>
        <Box display="flex" gap={1}>
          <Tooltip title="Actualizar">
            <IconButton onClick={refresh} disabled={loading}>
              <Refresh />
            </IconButton>
          </Tooltip>
          {(summary?.total_active ?? 0) > 0 && (
            <Button
              variant="outlined"
              color="success"
              startIcon={acking ? <CircularProgress size={16} /> : <DoneAll />}
              onClick={handleAckAll}
              disabled={acking}
            >
              Reconocer todas
            </Button>
          )}
        </Box>
      </Box>

      {loading && <LinearProgress sx={{ mb: 2 }} />}

      {/* ── KPI Cards ── */}
      <Grid container spacing={2} mb={3}>
        <Grid item xs={6} sm={3}>
          <SummaryCard
            label="Críticas"
            count={summary?.by_severity.CRITICAL ?? 0}
            color="#d32f2f"
            icon={<ErrorIcon fontSize="large" />}
            active={(summary?.by_severity.CRITICAL ?? 0) > 0}
          />
        </Grid>
        <Grid item xs={6} sm={3}>
          <SummaryCard
            label="Altas"
            count={summary?.by_severity.HIGH ?? 0}
            color="#ed6c02"
            icon={<Warning fontSize="large" />}
            active={(summary?.by_severity.HIGH ?? 0) > 0}
          />
        </Grid>
        <Grid item xs={6} sm={3}>
          <SummaryCard
            label="Medias"
            count={summary?.by_severity.MEDIUM ?? 0}
            color="#0288d1"
            icon={<Info fontSize="large" />}
            active={(summary?.by_severity.MEDIUM ?? 0) > 0}
          />
        </Grid>
        <Grid item xs={6} sm={3}>
          <SummaryCard
            label="Bajas"
            count={summary?.by_severity.LOW ?? 0}
            color="#757575"
            icon={<NotificationsOff fontSize="large" />}
            active={false}
          />
        </Grid>
      </Grid>

      {/* ── Por fuente ── */}
      {summary && Object.entries(summary.by_source).some(([, v]) => v > 0) && (
        <Box display="flex" gap={1} flexWrap="wrap" mb={2}>
          {(Object.entries(summary.by_source) as [AlertSource, number][])
            .filter(([, count]) => count > 0)
            .map(([src, count]) => (
              <Chip
                key={src}
                icon={SOURCE_ICON[src]}
                label={`${SOURCE_LABEL[src]}: ${count}`}
                size="small"
                variant="outlined"
              />
            ))
          }
        </Box>
      )}

      {/* ── Tabs + tabla ── */}
      <Card>
        <Tabs
          value={tab}
          onChange={(_, v) => setTab(v)}
          variant="scrollable"
          scrollButtons="auto"
          sx={{ borderBottom: 1, borderColor: 'divider', px: 2 }}
        >
          {TABS.map((label, i) => (
            <Tab
              key={label}
              label={
                <Badge badgeContent={unreadByTab[i]} color={i === 1 ? 'error' : i === 2 ? 'warning' : 'primary'} max={99}>
                  <Box sx={{ pr: unreadByTab[i] > 0 ? 1.5 : 0 }}>{label}</Box>
                </Badge>
              }
            />
          ))}
        </Tabs>

        {visible.length === 0 ? (
          <Box p={6} textAlign="center">
            <CheckCircle sx={{ fontSize: 56, color: 'success.main', mb: 1, opacity: 0.5 }} />
            <Typography variant="h6" color="text.secondary">Sin alertas {filteredSev ? `de nivel ${SEV_CONFIG[filteredSev].label.toLowerCase()}` : 'activas'}</Typography>
          </Box>
        ) : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell sx={{ width: 8, p: 0 }} />
                  <TableCell>Severidad</TableCell>
                  <TableCell>Fuente</TableCell>
                  <TableCell>Detalle</TableCell>
                  <TableCell>Hace</TableCell>
                  <TableCell align="right">Acciones</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {visible.map(alert => (
                  <AlertRow
                    key={alert.id}
                    alert={alert}
                    onAck={handleAck}
                    onView={setSelected}
                  />
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Card>

      {/* ── Detail dialog ── */}
      {selected && (
        <DetailDialog
          alert={selected}
          onClose={() => setSelected(null)}
          onAck={handleAck}
        />
      )}
    </Box>
  );
};

export default AlertasPage;
