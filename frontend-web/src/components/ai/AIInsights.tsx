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

function SeverityChip({ severity }: { severity?: string }) {
  const color = SEVERITY_COLOR[severity ?? 'LOW'] ?? TOKENS.green;
  return (
    <Chip
      size="small"
      label={severity ?? 'INFO'}
      sx={{ bgcolor: alpha(color, 0.12), color: color, fontWeight: 700, fontSize: '0.65rem', height: 18 }}
    />
  );
}

function InsightCard({ insight, icon }: { insight: Insight; icon: React.ReactNode }) {
  return (
    <ListItem alignItems="flex-start" sx={{ px: 0, py: 1 }}>
      <ListItemIcon sx={{ minWidth: 36, mt: 0.5 }}>{icon}</ListItemIcon>
      <ListItemText
        primary={
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.25 }}>
            <Typography variant="body2" fontWeight={700}>{insight.title}</Typography>
            {insight.severity && <SeverityChip severity={insight.severity} />}
            {insight.branch && (
              <Chip size="small" label={insight.branch}
                sx={{ height: 16, fontSize: '0.6rem', bgcolor: alpha(TOKENS.blue, 0.1) }} />
            )}
          </Box>
        }
        secondary={
          <Typography variant="caption" color="text.secondary">{insight.message}</Typography>
        }
      />
    </ListItem>
  );
}

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
    <Box sx={{ display: 'flex', justifyContent: 'center', p: 6 }}>
      <CircularProgress />
    </Box>
  );

  if (error) return (
    <MuiAlert severity="error" sx={{ m: 2 }}>{error}</MuiAlert>
  );

  if (!data) return null;

  const { alerts, recommendations, anomalies, predictions, summary } = data;

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <AutoAwesome sx={{ color: TOKENS.blue, fontSize: 28 }} />
          <Box>
            <Typography variant="h5" fontWeight={800}>IA Insights</Typography>
            <Typography variant="caption" color="text.secondary">
              {data.company} · {new Date(data.generated_at).toLocaleString('es-BO')}
            </Typography>
          </Box>
        </Box>
        <Button startIcon={<Refresh />} onClick={load} size="small" variant="outlined">
          Actualizar
        </Button>
      </Box>

      {/* Summary KPIs */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        {[
          { label: 'Alertas', count: summary.alert_count, icon: <Warning />, color: TOKENS.red },
          { label: 'Anomalías', count: summary.anomaly_count, icon: <ErrorIcon />, color: TOKENS.amber },
          { label: 'Recomendaciones', count: summary.recommendation_count, icon: <TipsAndUpdates />, color: TOKENS.green },
        ].map(kpi => (
          <Grid item xs={12} sm={4} key={kpi.label}>
            <Card sx={{ border: `1px solid ${TOKENS.border}` }}>
              <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <Box sx={{ color: kpi.color, opacity: 0.8 }}>{kpi.icon}</Box>
                <Box>
                  <Typography variant="h4" fontWeight={800} sx={{ color: kpi.color, lineHeight: 1 }}>
                    {kpi.count}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">{kpi.label}</Typography>
                </Box>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      <Grid container spacing={3}>
        {/* Alerts */}
        {alerts.length > 0 && (
          <Grid item xs={12} md={6}>
            <Card sx={{ border: `1px solid ${TOKENS.border}` }}>
              <CardContent>
                <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Warning sx={{ fontSize: 18, color: TOKENS.red }} /> Alertas Activas
                </Typography>
                <Divider sx={{ mb: 1 }} />
                <List dense disablePadding>
                  {alerts.map((a, i) => (
                    <InsightCard key={i} insight={a}
                      icon={<Warning sx={{ color: SEVERITY_COLOR[a.severity ?? 'LOW'], fontSize: 18 }} />} />
                  ))}
                </List>
              </CardContent>
            </Card>
          </Grid>
        )}

        {/* Anomalies */}
        {anomalies.length > 0 && (
          <Grid item xs={12} md={6}>
            <Card sx={{ border: `1px solid ${TOKENS.border}` }}>
              <CardContent>
                <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Analytics sx={{ fontSize: 18, color: TOKENS.amber }} /> Anomalías Detectadas
                </Typography>
                <Divider sx={{ mb: 1 }} />
                <List dense disablePadding>
                  {anomalies.map((a, i) => (
                    <InsightCard key={i} insight={a}
                      icon={<ErrorIcon sx={{ color: SEVERITY_COLOR[a.severity ?? 'MEDIUM'], fontSize: 18 }} />} />
                  ))}
                </List>
              </CardContent>
            </Card>
          </Grid>
        )}

        {/* Recommendations */}
        {recommendations.length > 0 && (
          <Grid item xs={12} md={6}>
            <Card sx={{ border: `1px solid ${TOKENS.border}` }}>
              <CardContent>
                <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
                  <TipsAndUpdates sx={{ fontSize: 18, color: TOKENS.green }} /> Recomendaciones
                </Typography>
                <Divider sx={{ mb: 1 }} />
                <List dense disablePadding>
                  {recommendations.map((r, i) => (
                    <InsightCard key={i} insight={r}
                      icon={<CheckCircle sx={{ color: TOKENS.green, fontSize: 18 }} />} />
                  ))}
                </List>
              </CardContent>
            </Card>
          </Grid>
        )}

        {/* Transaction trend prediction */}
        {predictions.map((p, i) => p.type === 'TRANSACTION_TREND' && (
          <Grid item xs={12} md={6} key={i}>
            <Card sx={{ border: `1px solid ${TOKENS.border}` }}>
              <CardContent>
                <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
                  {p.trend === 'UP'   ? <TrendingUp   sx={{ color: TOKENS.green }} /> :
                   p.trend === 'DOWN' ? <TrendingDown sx={{ color: TOKENS.red }}   /> :
                                        <TrendingFlat sx={{ color: TOKENS.amber }} />}
                  {p.title}
                </Typography>
                <Divider sx={{ mb: 1.5 }} />
                <Typography variant="caption" color="text.secondary">{p.message}</Typography>
                <Box sx={{ display: 'flex', gap: 0.5, mt: 1.5, flexWrap: 'wrap' }}>
                  {p.daily?.map((d: any) => (
                    <Box key={d.date} sx={{ textAlign: 'center', minWidth: 32 }}>
                      <Typography variant="caption" sx={{ fontWeight: 800, fontSize: '0.75rem' }}>
                        {d.count}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ fontSize: '0.6rem' }}>
                        {new Date(d.date).toLocaleDateString('es-BO', { day: '2-digit', month: '2-digit' })}
                      </Typography>
                    </Box>
                  ))}
                </Box>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      {alerts.length === 0 && anomalies.length === 0 && recommendations.length === 0 && (
        <Box sx={{ textAlign: 'center', py: 6, color: 'text.secondary' }}>
          <CheckCircle sx={{ fontSize: 48, color: TOKENS.green, mb: 1 }} />
          <Typography variant="h6" fontWeight={700}>Sistema en estado óptimo</Typography>
          <Typography variant="body2">No se detectaron alertas ni anomalías.</Typography>
        </Box>
      )}
    </Box>
  );
}
