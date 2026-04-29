import React, { useEffect, useState, useCallback } from 'react';
import {
  Box, Grid, Typography, Chip, Card, CardContent,
  CircularProgress, Alert as MuiAlert, Button,
  Divider, List, ListItem, ListItemIcon, ListItemText,
} from '@mui/material';
import {
  AutoAwesome, Warning, TipsAndUpdates, Analytics,
  TrendingUp, TrendingDown, TrendingFlat, Refresh,
  Error as ErrorIcon, CheckCircle,
} from '@mui/icons-material';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from '../../services/api';
import { TOKENS } from '../../styles/theme';
import { alpha } from '@mui/material/styles';

interface Insight {
  type:     string;
  severity?: string;
  title:    string;
  message:  string;
  [key: string]: any;
}

interface InsightsData {
  company:         string | null;
  generated_at:    string;
  alerts:          Insight[];
  recommendations: Insight[];
  anomalies:       Insight[];
  predictions:     Insight[];
  summary: {
    alert_count:          number;
    anomaly_count:        number;
    recommendation_count: number;
  };
}

const SEVERITY_COLOR: Record<string, string> = {
  CRITICAL: TOKENS.red,
  HIGH:     TOKENS.red,
  MEDIUM:   TOKENS.amber,
  LOW:      TOKENS.green,
};

// ── Sub-components ────────────────────────────────────────────────────────────

function SeverityChip({ severity }: { severity?: string }) {
  const color = SEVERITY_COLOR[severity ?? 'LOW'] ?? TOKENS.green;
  return (
    <Chip
      size="small" label={severity ?? 'INFO'}
      sx={{ bgcolor: alpha(color, 0.12), color, fontWeight: 700, fontSize: '0.65rem', height: 18 }}
    />
  );
}

function InsightRow({ insight, icon, delay = 0 }: { insight: Insight; icon: React.ReactNode; delay?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.22, delay, ease: 'easeOut' }}
    >
      <Box sx={{
        display: 'flex', alignItems: 'flex-start', gap: 1.25,
        py: 1.25, px: 1.5, borderRadius: 2, mb: 0.75,
        bgcolor: alpha(TOKENS.bg, 0.6),
        border: `1px solid ${TOKENS.border}`,
        transition: 'background-color 0.15s',
        '&:hover': { bgcolor: TOKENS.surface, borderColor: alpha(TOKENS.blue, 0.2) },
      }}>
        <Box sx={{ mt: 0.125, flexShrink: 0 }}>{icon}</Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mb: 0.25, flexWrap: 'wrap' }}>
            <Typography variant="body2" fontWeight={700}>{insight.title}</Typography>
            {insight.severity && <SeverityChip severity={insight.severity} />}
            {insight.branch && (
              <Chip size="small" label={insight.branch}
                sx={{ height: 16, fontSize: '0.6rem', bgcolor: alpha(TOKENS.blue, 0.1), color: TOKENS.blue }} />
            )}
          </Box>
          <Typography variant="caption" color="text.secondary" sx={{ lineHeight: 1.4 }}>
            {insight.message}
          </Typography>
        </Box>
      </Box>
    </motion.div>
  );
}

function SectionCard({
  title, icon, accentColor, items, renderRow, emptyLabel,
}: {
  title:      string;
  icon:       React.ReactNode;
  accentColor:string;
  items:      Insight[];
  renderRow:  (item: Insight, i: number) => React.ReactNode;
  emptyLabel: string;
}) {
  return (
    <Card sx={{ height: '100%', position: 'relative', overflow: 'hidden' }}>
      <Box sx={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, bgcolor: accentColor, borderRadius: '14px 14px 0 0' }} />
      <CardContent sx={{ pt: 2.5 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
          <Box sx={{ color: accentColor, display: 'flex' }}>{icon}</Box>
          <Typography variant="subtitle1" fontWeight={700}>{title}</Typography>
          <Chip label={items.length} size="small"
            sx={{ height: 18, fontSize: '0.65rem', fontWeight: 700, bgcolor: alpha(accentColor, 0.12), color: accentColor, ml: 'auto' }} />
        </Box>
        <Divider sx={{ mb: 1.5 }} />
        {items.length === 0 ? (
          <Box sx={{ py: 3, textAlign: 'center' }}>
            <CheckCircle sx={{ fontSize: 32, color: alpha(TOKENS.green, 0.4), mb: 0.75 }} />
            <Typography variant="body2" color="text.secondary">{emptyLabel}</Typography>
          </Box>
        ) : (
          items.map((item, i) => renderRow(item, i))
        )}
      </CardContent>
    </Card>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function AIInsights() {
  const [data,    setData]    = useState<InsightsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get('/ai/insights/');
      setData(res.data);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Error al cargar insights');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return (
    <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', p: 8, gap: 2 }}>
      <CircularProgress size={32} />
      <Typography variant="body2" color="text.secondary">Analizando datos con IA…</Typography>
    </Box>
  );

  if (error) return (
    <MuiAlert severity="error" sx={{ m: 2 }}
      action={<Button size="small" color="inherit" onClick={load}>Reintentar</Button>}>
      {error}
    </MuiAlert>
  );

  if (!data) return null;

  const { alerts, recommendations, anomalies, predictions, summary } = data;
  const allClear = alerts.length === 0 && anomalies.length === 0 && recommendations.length === 0;

  return (
    <Box>
      {/* ── Premium header ── */}
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 3 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <Box sx={{
              width: 40, height: 40, borderRadius: '11px',
              background: `linear-gradient(135deg, ${TOKENS.blue} 0%, #7C3AED 100%)`,
              display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
              boxShadow: `0 4px 14px ${alpha(TOKENS.blue, 0.35)}`,
            }}>
              <AutoAwesome sx={{ color: 'white', fontSize: 20 }} />
            </Box>
            <Box>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Typography variant="h4" fontWeight={800}>IA Insights</Typography>
                <Chip label="LIVE" size="small" color="success" sx={{ height: 20, fontSize: '0.6rem', fontWeight: 800 }} />
              </Box>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.125 }}>
                {data.company} · {new Date(data.generated_at).toLocaleString('es-BO')}
              </Typography>
            </Box>
          </Box>
          <Button
            startIcon={<Refresh />} onClick={load} size="small" variant="outlined"
            sx={{ borderRadius: '8px', fontWeight: 600 }}
          >
            Actualizar
          </Button>
        </Box>
      </motion.div>

      {/* ── Summary KPI strip ── */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        {[
          {
            label: 'Alertas activas',
            count: summary.alert_count,
            icon: <Warning sx={{ fontSize: 18 }} />,
            color: summary.alert_count > 0 ? TOKENS.red : TOKENS.green,
            hint:  summary.alert_count > 0 ? 'requieren atención' : 'sin alertas',
          },
          {
            label: 'Anomalías',
            count: summary.anomaly_count,
            icon: <ErrorIcon sx={{ fontSize: 18 }} />,
            color: summary.anomaly_count > 0 ? TOKENS.amber : TOKENS.green,
            hint:  summary.anomaly_count > 0 ? 'patrones inusuales' : 'comportamiento normal',
          },
          {
            label: 'Recomendaciones',
            count: summary.recommendation_count,
            icon: <TipsAndUpdates sx={{ fontSize: 18 }} />,
            color: TOKENS.blue,
            hint:  'acciones sugeridas',
          },
        ].map((kpi, i) => (
          <Grid item xs={12} sm={4} key={kpi.label}>
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25, delay: i * 0.07 }}
            >
              <Card sx={{
                position: 'relative', overflow: 'hidden',
                bgcolor: alpha(kpi.color, 0.04),
                borderColor: alpha(kpi.color, 0.2),
              }}>
                <Box sx={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, bgcolor: kpi.color, borderRadius: '14px 14px 0 0' }} />
                <CardContent>
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <Box>
                      <Typography variant="overline" color="text.secondary" sx={{ fontSize: '0.65rem' }}>
                        {kpi.label}
                      </Typography>
                      <Typography variant="h3" fontWeight={800} sx={{ color: kpi.color, lineHeight: 1.1, fontVariantNumeric: 'tabular-nums' }}>
                        {kpi.count}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">{kpi.hint}</Typography>
                    </Box>
                    <Box sx={{ width: 40, height: 40, borderRadius: '11px', bgcolor: alpha(kpi.color, 0.1), display: 'flex', alignItems: 'center', justifyContent: 'center', color: kpi.color }}>
                      {kpi.icon}
                    </Box>
                  </Box>
                </CardContent>
              </Card>
            </motion.div>
          </Grid>
        ))}
      </Grid>

      {/* ── All-clear state ── */}
      <AnimatePresence>
        {allClear && (
          <motion.div
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
          >
            <Box sx={{
              textAlign: 'center', py: 6,
              bgcolor: alpha(TOKENS.green, 0.05),
              border: `1px solid ${alpha(TOKENS.green, 0.2)}`,
              borderRadius: 3,
            }}>
              <CheckCircle sx={{ fontSize: 52, color: TOKENS.green, mb: 1.5 }} />
              <Typography variant="h5" fontWeight={800} sx={{ color: TOKENS.green, mb: 0.5 }}>
                Sistema en estado óptimo
              </Typography>
              <Typography variant="body2" color="text.secondary">
                No se detectaron alertas, anomalías ni recomendaciones pendientes.
              </Typography>
            </Box>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Insight sections ── */}
      {!allClear && (
        <Grid container spacing={3}>
          {/* Alerts */}
          <Grid item xs={12} md={6}>
            <SectionCard
              title="Alertas Activas" accentColor={TOKENS.red}
              icon={<Warning sx={{ fontSize: 18 }} />}
              items={alerts}
              emptyLabel="Sin alertas activas"
              renderRow={(a, i) => (
                <InsightRow key={i} insight={a} delay={i * 0.04}
                  icon={<Warning sx={{ color: SEVERITY_COLOR[a.severity ?? 'LOW'], fontSize: 16 }} />} />
              )}
            />
          </Grid>

          {/* Anomalies */}
          <Grid item xs={12} md={6}>
            <SectionCard
              title="Anomalías Detectadas" accentColor={TOKENS.amber}
              icon={<Analytics sx={{ fontSize: 18 }} />}
              items={anomalies}
              emptyLabel="Comportamiento normal detectado"
              renderRow={(a, i) => (
                <InsightRow key={i} insight={a} delay={i * 0.04}
                  icon={<ErrorIcon sx={{ color: SEVERITY_COLOR[a.severity ?? 'MEDIUM'], fontSize: 16 }} />} />
              )}
            />
          </Grid>

          {/* Recommendations */}
          {recommendations.length > 0 && (
            <Grid item xs={12} md={6}>
              <SectionCard
                title="Recomendaciones" accentColor={TOKENS.green}
                icon={<TipsAndUpdates sx={{ fontSize: 18 }} />}
                items={recommendations}
                emptyLabel="Sin recomendaciones"
                renderRow={(r, i) => (
                  <InsightRow key={i} insight={r} delay={i * 0.04}
                    icon={<CheckCircle sx={{ color: TOKENS.green, fontSize: 16 }} />} />
                )}
              />
            </Grid>
          )}

          {/* Transaction trend prediction */}
          {predictions.filter(p => p.type === 'TRANSACTION_TREND').map((p, i) => (
            <Grid item xs={12} md={6} key={`pred-${i}`}>
              <Card sx={{ position: 'relative', overflow: 'hidden' }}>
                <Box sx={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, bgcolor: TOKENS.blue, borderRadius: '14px 14px 0 0' }} />
                <CardContent sx={{ pt: 2.5 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
                    {p.trend === 'UP'
                      ? <TrendingUp   sx={{ color: TOKENS.green }} />
                      : p.trend === 'DOWN'
                        ? <TrendingDown sx={{ color: TOKENS.red }} />
                        : <TrendingFlat sx={{ color: TOKENS.amber }} />
                    }
                    <Typography variant="subtitle1" fontWeight={700}>{p.title}</Typography>
                  </Box>
                  <Divider sx={{ mb: 1.5 }} />
                  <Typography variant="caption" color="text.secondary">{p.message}</Typography>
                  {p.daily && (
                    <Box sx={{ display: 'flex', gap: 1, mt: 2, flexWrap: 'wrap' }}>
                      {p.daily.map((d: any) => (
                        <Box key={d.date} sx={{
                          textAlign: 'center', minWidth: 36, py: 0.75, px: 1,
                          borderRadius: 1, bgcolor: alpha(TOKENS.blue, 0.06),
                          border: `1px solid ${alpha(TOKENS.blue, 0.1)}`,
                        }}>
                          <Typography variant="body2" fontWeight={800} sx={{ color: TOKENS.blue, lineHeight: 1 }}>
                            {d.count}
                          </Typography>
                          <Typography variant="caption" color="text.secondary" display="block" sx={{ fontSize: '0.6rem', mt: 0.25 }}>
                            {new Date(d.date).toLocaleDateString('es-BO', { day: '2-digit', month: '2-digit' })}
                          </Typography>
                        </Box>
                      ))}
                    </Box>
                  )}
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}
    </Box>
  );
}
