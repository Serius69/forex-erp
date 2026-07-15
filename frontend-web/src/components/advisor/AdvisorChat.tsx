/**
 * Asesor de Divisas — chat que responde "¿compro o no?" componiendo las
 * señales REALES del sistema: pronóstico ML, brecha oficial BCB↔paralelo,
 * sentimiento de noticias (RSS), Monte Carlo, posición de inventario y el
 * motor AI de pricing. Backend: POST /api/predictions/advisor/.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert, Box, Card, CardContent, Chip, CircularProgress, IconButton,
  Paper, TextField, Tooltip, Typography,
} from '@mui/material';
import {
  Send, SmartToy, Person, TrendingUp, TrendingDown, RemoveCircleOutline,
  Newspaper, ShowChart, AccountBalance, Casino, Inventory2,
} from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';

interface AdvisorResponse {
  currency: string;
  decision: 'COMPRAR' | 'ESPERAR' | 'VENDER';
  score: number;
  confidence: number;
  reply: string;
  signals: Record<string, any>;
}

interface Msg {
  role: 'user' | 'bot';
  text: string;
  data?: AdvisorResponse;
  ts: number;
}

const QUICK = [
  '¿Compro dólares hoy?',
  '¿Vendo mis dólares?',
  '¿Compro euros?',
  '¿Cómo ves el sol peruano?',
];

const DECISION_META: Record<string, { color: 'success' | 'warning' | 'error'; icon: React.ReactNode }> = {
  COMPRAR: { color: 'success', icon: <TrendingUp fontSize="small" /> },
  ESPERAR: { color: 'warning', icon: <RemoveCircleOutline fontSize="small" /> },
  VENDER:  { color: 'error',   icon: <TrendingDown fontSize="small" /> },
};

const SignalChips: React.FC<{ signals: Record<string, any> }> = ({ signals }) => {
  const chips: { icon: React.ReactNode; label: string; tip: string }[] = [];
  const f = signals.forecast;
  if (f) chips.push({
    icon: <ShowChart fontSize="small" />,
    label: `ML ${f.delta_pct > 0 ? '+' : ''}${f.delta_pct}% 24h`,
    tip: `Ensemble (serie ${f.market}): ${f.current_rate} → ${f.predicted_rate}`,
  });
  const s = signals.sentimiento;
  if (s) chips.push({
    icon: <Newspaper fontSize="small" />,
    label: `Noticias ${s.index > 0 ? '+' : ''}${(s.index).toFixed(2)}`,
    tip: s.headline ?? 'Índice de sentimiento (RSS, 48h)',
  });
  const b = signals.brecha;
  if (b) chips.push({
    icon: <AccountBalance fontSize="small" />,
    label: `Brecha BCB ${b.brecha_pct}%`,
    tip: `Oficial↔paralelo, tendencia ${b.tendencia_pp > 0 ? '+' : ''}${b.tendencia_pp}pp/7d`,
  });
  const m = signals.montecarlo;
  if (m) chips.push({
    icon: <Casino fontSize="small" />,
    label: `P(sube 7d) ${(m.prob_sube_7d * 100).toFixed(0)}%`,
    tip: `Monte Carlo bootstrap · σ anual ${m.sigma_anual_pct}%`,
  });
  const p = signals.posicion;
  if (p?.stock) chips.push({
    icon: <Inventory2 fontSize="small" />,
    label: `Stock ${Number(p.stock).toLocaleString()}${p.stock_pct_max ? ` (${p.stock_pct_max}%)` : ''}`,
    tip: 'Posición actual en inventario (% del máximo configurado)',
  });
  if (!chips.length) return null;
  return (
    <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 1 }}>
      {chips.map((c, i) => (
        <Tooltip key={i} title={c.tip}>
          <Chip size="small" variant="outlined" icon={c.icon as any} label={c.label} />
        </Tooltip>
      ))}
    </Box>
  );
};

const BotBubble: React.FC<{ msg: Msg }> = ({ msg }) => {
  const d = msg.data;
  const meta = d ? DECISION_META[d.decision] : null;
  // texto: negritas markdown simples + bullets
  const lines = msg.text.split('\n').filter(Boolean);
  return (
    <Paper variant="outlined" sx={{ p: 1.5, maxWidth: '85%', bgcolor: 'background.default' }}>
      {d && meta && (
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mb: 1 }}>
          <Chip color={meta.color} icon={meta.icon as any}
                label={`${d.decision} ${d.currency}`} size="small" />
          <Typography variant="caption" color="text.secondary">
            confianza {(d.confidence * 100).toFixed(0)}% · score {d.score > 0 ? '+' : ''}{d.score}
          </Typography>
        </Box>
      )}
      {lines.map((ln, i) => (
        <Typography key={i} variant="body2"
                    sx={{ mb: 0.5, fontStyle: ln.startsWith('_') ? 'italic' : undefined,
                          color: ln.startsWith('_') ? 'text.secondary' : undefined,
                          fontSize: ln.startsWith('_') ? '0.72rem' : undefined }}>
          {ln.replace(/\*\*/g, '').replace(/^_|_$/g, '')}
        </Typography>
      ))}
      {d && <SignalChips signals={d.signals} />}
    </Paper>
  );
};

const AdvisorChat: React.FC = () => {
  const { enqueueSnackbar } = useSnackbar();
  const [messages, setMessages] = useState<Msg[]>([{
    role: 'bot', ts: Date.now(),
    text: 'Hola — soy el asesor de divisas de Kapitalya. Pregúntame si conviene '
        + 'comprar o vender una divisa y te respondo con las señales reales del '
        + 'sistema: pronóstico ML, brecha oficial BCB, noticias, simulación y tu '
        + 'inventario.',
  }]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const ask = useCallback(async (text: string) => {
    const q = text.trim();
    if (!q || busy) return;
    setMessages(m => [...m, { role: 'user', text: q, ts: Date.now() }]);
    setInput('');
    setBusy(true);
    try {
      const res = await api.post('/predictions/advisor/', { message: q });
      const d: AdvisorResponse = res.data;
      setMessages(m => [...m, { role: 'bot', text: d.reply, data: d, ts: Date.now() }]);
    } catch (e: any) {
      const msg = e?.response?.data?.error ?? 'El asesor no está disponible';
      enqueueSnackbar(msg, { variant: 'error' });
      setMessages(m => [...m, {
        role: 'bot', ts: Date.now(),
        text: `No pude analizar eso ahora (${msg}). Intenta de nuevo en un momento.`,
      }]);
    } finally {
      setBusy(false);
    }
  }, [busy, enqueueSnackbar]);

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, display: 'flex', flexDirection: 'column',
               height: 'calc(100vh - 120px)' }}>
      <Typography variant="h5" fontWeight={700} gutterBottom>
        Asesor de Divisas
      </Typography>
      <Alert severity="info" sx={{ mb: 2 }}>
        Lectura estadística de señales reales (ML, BCB, noticias, inventario) —
        referencia operativa, no asesoría financiera definitiva.
      </Alert>

      <Card variant="outlined" sx={{ flex: 1, display: 'flex', flexDirection: 'column',
                                     overflow: 'hidden' }}>
        <CardContent sx={{ flex: 1, overflowY: 'auto', display: 'flex',
                           flexDirection: 'column', gap: 1.5 }}>
          {messages.map((m, i) => (
            <Box key={i} sx={{ display: 'flex', gap: 1,
                               justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
              {m.role === 'bot' && <SmartToy color="primary" sx={{ mt: 0.5 }} />}
              {m.role === 'user' ? (
                <Paper sx={{ p: 1.5, maxWidth: '75%', bgcolor: 'primary.main',
                             color: 'primary.contrastText' }}>
                  <Typography variant="body2">{m.text}</Typography>
                </Paper>
              ) : (
                <BotBubble msg={m} />
              )}
              {m.role === 'user' && <Person color="action" sx={{ mt: 0.5 }} />}
            </Box>
          ))}
          {busy && (
            <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
              <SmartToy color="primary" />
              <CircularProgress size={16} />
              <Typography variant="caption" color="text.secondary">
                analizando señales…
              </Typography>
            </Box>
          )}
          <div ref={endRef} />
        </CardContent>

        <Box sx={{ p: 1.5, borderTop: 1, borderColor: 'divider' }}>
          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mb: 1 }}>
            {QUICK.map(q => (
              <Chip key={q} label={q} size="small" variant="outlined"
                    onClick={() => ask(q)} disabled={busy} sx={{ cursor: 'pointer' }} />
            ))}
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <TextField
              fullWidth size="small" placeholder="¿Compro dólares hoy?"
              value={input} onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') ask(input); }}
              disabled={busy}
            />
            <IconButton color="primary" onClick={() => ask(input)}
                        disabled={busy || !input.trim()}>
              <Send />
            </IconButton>
          </Box>
        </Box>
      </Card>
    </Box>
  );
};

export default AdvisorChat;
