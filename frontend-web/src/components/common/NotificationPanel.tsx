/**
 * NotificationPanel — Drawer de alertas del sistema.
 *
 * Features:
 *  - Tabs de filtro por severidad (Todas / Críticas / Altas / Medias / Bajas)
 *  - Badge de no-reconocidas por tab
 *  - Acknowledge individual + "Reconocer todas"
 *  - Timestamp relativo + chip de fuente
 *  - Estado vacío por tab
 */
import React, { useState } from 'react';
import {
  Drawer, Box, Typography, IconButton, List, ListItem,
  ListItemText, ListItemIcon, Chip, Divider, Button,
  Tab, Tabs, Tooltip, CircularProgress, Badge,
} from '@mui/material';
import {
  Close, Warning, Error as ErrorIcon, Info, CheckCircle,
  DoneAll, Refresh,
} from '@mui/icons-material';
import { formatDistanceToNow } from 'date-fns';
import { es } from 'date-fns/locale';
import { AlertLogEntry, AlertSeverity, AlertSource, useAlerts } from '../../hooks/useAlerts';

// ── Severity config ───────────────────────────────────────────────────────────

const SEV_CONFIG: Record<AlertSeverity, {
  label: string; color: 'error' | 'warning' | 'info' | 'default'; icon: React.ReactElement;
}> = {
  CRITICAL: { label: 'Crítica',  color: 'error',   icon: <ErrorIcon color="error"   /> },
  HIGH:     { label: 'Alta',     color: 'warning',  icon: <Warning  color="warning"  /> },
  MEDIUM:   { label: 'Media',    color: 'info',     icon: <Info     color="info"     /> },
  LOW:      { label: 'Baja',     color: 'default',  icon: <Info     color="disabled" /> },
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

// ── Sub-components ────────────────────────────────────────────────────────────

const AlertItem: React.FC<{
  alert: AlertLogEntry;
  onAcknowledge: (id: string) => void;
}> = ({ alert, onAcknowledge }) => {
  const sev  = SEV_CONFIG[alert.severity] ?? SEV_CONFIG.LOW;
  const time = (() => {
    try {
      return formatDistanceToNow(new Date(alert.created_at), { addSuffix: true, locale: es });
    } catch {
      return alert.created_at;
    }
  })();

  return (
    <ListItem
      alignItems="flex-start"
      sx={{
        bgcolor:      alert.is_acknowledged ? 'transparent' : 'action.hover',
        borderRadius: 1,
        mb:           0.5,
        px:           1,
        gap:          1,
        borderLeft:   `3px solid`,
        borderColor:  alert.is_acknowledged
          ? 'divider'
          : sev.color === 'error'   ? 'error.main'
          : sev.color === 'warning' ? 'warning.main'
          : sev.color === 'info'    ? 'info.main'
          : 'divider',
      }}
    >
      <ListItemIcon sx={{ minWidth: 32, mt: 0.5 }}>{sev.icon}</ListItemIcon>

      <ListItemText
        primary={
          <Box display="flex" alignItems="center" gap={0.5} flexWrap="wrap">
            <Typography variant="body2" fontWeight={alert.is_acknowledged ? 400 : 700}>
              {alert.title}
            </Typography>
            <Chip
              label={SOURCE_LABEL[alert.source] ?? alert.source}
              size="small"
              variant="outlined"
              sx={{ height: 18, fontSize: 10 }}
            />
          </Box>
        }
        secondary={
          <Box>
            <Typography variant="caption" color="text.secondary" display="block">
              {alert.message}
            </Typography>
            <Typography variant="caption" color="text.disabled">
              {time}
              {alert.acknowledged_by_name && ` · ✓ ${alert.acknowledged_by_name}`}
            </Typography>
          </Box>
        }
      />

      {!alert.is_acknowledged && (
        <Tooltip title="Reconocer">
          <IconButton
            size="small"
            onClick={() => onAcknowledge(alert.id)}
            sx={{ alignSelf: 'center', ml: 'auto', flexShrink: 0 }}
          >
            <CheckCircle fontSize="small" />
          </IconButton>
        </Tooltip>
      )}
    </ListItem>
  );
};

// ── Main component ────────────────────────────────────────────────────────────

interface NotificationPanelProps {
  open:    boolean;
  onClose: () => void;
}

type TabFilter = 'ALL' | AlertSeverity;

const TABS: { value: TabFilter; label: string }[] = [
  { value: 'ALL',      label: 'Todas'    },
  { value: 'CRITICAL', label: 'Críticas' },
  { value: 'HIGH',     label: 'Altas'    },
  { value: 'MEDIUM',   label: 'Medias'   },
  { value: 'LOW',      label: 'Bajas'    },
];

const NotificationPanel: React.FC<NotificationPanelProps> = ({ open, onClose }) => {
  const [tab, setTab] = useState<TabFilter>('ALL');
  const { alerts, summary, loading, unacknowledged, acknowledge, acknowledgeAll, refresh } =
    useAlerts();

  const visible = tab === 'ALL' ? alerts : alerts.filter(a => a.severity === tab);

  const countUnackForTab = (t: TabFilter): number => {
    if (!summary) return 0;
    if (t === 'ALL') return summary.total_active;
    return summary.by_severity[t as AlertSeverity] ?? 0;
  };

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{ sx: { width: { xs: '100vw', sm: 420 }, maxWidth: '100%', display: 'flex', flexDirection: 'column' } }}
    >
      {/* ── Header ── */}
      <Box sx={{ p: 2, pb: 1 }}>
        <Box display="flex" justifyContent="space-between" alignItems="center">
          <Typography variant="h6" fontWeight={700}>
            Alertas del sistema
            {unacknowledged > 0 && (
              <Chip
                label={unacknowledged}
                size="small"
                color="error"
                sx={{ ml: 1, height: 20, fontSize: 11, fontWeight: 700 }}
              />
            )}
          </Typography>
          <Box display="flex" gap={0.5}>
            <Tooltip title="Actualizar">
              <IconButton size="small" onClick={refresh} disabled={loading}>
                {loading ? <CircularProgress size={18} /> : <Refresh fontSize="small" />}
              </IconButton>
            </Tooltip>
            <IconButton size="small" onClick={onClose}><Close /></IconButton>
          </Box>
        </Box>

        {unacknowledged > 0 && (
          <Button
            size="small"
            startIcon={<DoneAll />}
            onClick={() => acknowledgeAll(tab === 'ALL' ? undefined : tab as AlertSource)}
            sx={{ mt: 0.5 }}
          >
            Reconocer {tab === 'ALL' ? 'todas' : 'visibles'}
          </Button>
        )}
      </Box>

      {/* ── Severity tabs ── */}
      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        variant="scrollable"
        scrollButtons="auto"
        sx={{ borderBottom: 1, borderColor: 'divider', minHeight: 36 }}
      >
        {TABS.map(t => {
          const count = countUnackForTab(t.value);
          return (
            <Tab
              key={t.value}
              value={t.value}
              label={
                <Badge badgeContent={count || 0} color="error" max={99}
                  invisible={count === 0}
                  sx={{ '& .MuiBadge-badge': { fontSize: 9, height: 14, minWidth: 14 } }}>
                  <Typography variant="caption" fontWeight={600}>{t.label}</Typography>
                </Badge>
              }
              sx={{ minHeight: 36, py: 0.5 }}
            />
          );
        })}
      </Tabs>

      {/* ── Alert list ── */}
      <Box sx={{ flex: 1, overflow: 'auto', p: 1 }}>
        {loading && alerts.length === 0 ? (
          <Box display="flex" justifyContent="center" py={6}>
            <CircularProgress size={32} />
          </Box>
        ) : visible.length === 0 ? (
          <Box textAlign="center" py={6}>
            <CheckCircle sx={{ fontSize: 48, color: 'success.light', mb: 1 }} />
            <Typography variant="body2" color="text.secondary">
              {tab === 'ALL' ? 'No hay alertas' : `No hay alertas ${TABS.find(t => t.value === tab)?.label.toLowerCase()}`}
            </Typography>
          </Box>
        ) : (
          <List dense disablePadding>
            {visible.map(alert => (
              <AlertItem key={alert.id} alert={alert} onAcknowledge={acknowledge} />
            ))}
          </List>
        )}
      </Box>

      {/* ── Summary footer ── */}
      {summary && (
        <>
          <Divider />
          <Box sx={{ p: 1.5, display: 'flex', gap: 0.75, flexWrap: 'wrap' }}>
            {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as AlertSeverity[]).map(sev => {
              const n = summary.by_severity[sev] ?? 0;
              if (n === 0) return null;
              const cfg = SEV_CONFIG[sev];
              return (
                <Chip
                  key={sev}
                  label={`${cfg.label}: ${n}`}
                  color={cfg.color}
                  size="small"
                  variant="outlined"
                  onClick={() => setTab(sev)}
                  sx={{ cursor: 'pointer', fontSize: 11 }}
                />
              );
            })}
          </Box>
        </>
      )}
    </Drawer>
  );
};

export default NotificationPanel;
