/**
 * Analista — chat de inteligencia de negocio. Responde en lenguaje natural
 * sobre cómo va el negocio, ganancias, tasas, pronósticos, macro e inventario,
 * anclado en los datos REALES del sistema (backend POST /api/analytics/assistant/).
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert, Box, Card, CardContent, Chip, CircularProgress, IconButton,
  Paper, TextField, Typography,
} from '@mui/material';
import {
  Send, Insights, Person, TrendingUp, AttachMoney, ShowChart,
  Public, Inventory2, HelpOutline, Timeline,
} from '@mui/icons-material';
import { useSnackbar } from 'notistack';
import { api } from '../../services/api';

interface AssistantResponse {
  intent: string;
  reply: string;
  data?: Record<string, any>;
}

interface Msg { role: 'user' | 'bot'; text: string; intent?: string; ts: number; }

const QUICK = [
  '¿Cómo va el negocio hoy?',
  '¿Qué divisa dio más ganancia este mes?',
  '¿A cuánto está el dólar?',
  '¿Qué pasará con el dólar?',
  '¿Cómo está la economía?',
  '¿Cuánto USD tenemos?',
];

const INTENT_META: Record<string, { label: string; icon: React.ReactNode; color: any }> = {
  negocio:      { label: 'Negocio',     icon: <TrendingUp fontSize="inherit" />,  color: 'success' },
  ganancia:     { label: 'Ganancias',   icon: <AttachMoney fontSize="inherit" />, color: 'success' },
  tasas:        { label: 'Tasas',       icon: <ShowChart fontSize="inherit" />,   color: 'primary' },
  pronostico:   { label: 'Pronóstico',  icon: <Timeline fontSize="inherit" />,    color: 'info' },
  compra_venta: { label: 'Asesoría',    icon: <ShowChart fontSize="inherit" />,   color: 'warning' },
  macro:        { label: 'Macro',       icon: <Public fontSize="inherit" />,      color: 'info' },
  inventario:   { label: 'Inventario',  icon: <Inventory2 fontSize="inherit" />,  color: 'default' },
  saludo:       { label: 'Ayuda',       icon: <HelpOutline fontSize="inherit" />, color: 'default' },
  ayuda:        { label: 'Ayuda',       icon: <HelpOutline fontSize="inherit" />, color: 'default' },
};

const BotBubble: React.FC<{ msg: Msg }> = ({ msg }) => {
  const meta = msg.intent ? INTENT_META[msg.intent] : null;
  const lines = msg.text.split('\n').filter(Boolean);
  return (
    <Paper variant="outlined" sx={{ p: 1.5, maxWidth: '85%', bgcolor: 'background.default' }}>
      {meta && (
        <Chip size="small" color={meta.color} icon={meta.icon as any}
              label={meta.label} sx={{ mb: 1, fontSize: '0.68rem', height: 22 }} />
      )}
      {lines.map((ln, i) => {
        const bullet = ln.trim().startsWith('•');
        return (
          <Typography key={i} variant="body2"
                      sx={{ mb: 0.4, pl: bullet ? 1 : 0,
                            fontStyle: ln.startsWith('_') ? 'italic' : undefined,
                            color: ln.startsWith('_') ? 'text.secondary' : undefined }}>
            {ln.replace(/\*\*/g, '').replace(/^_|_$/g, '')}
          </Typography>
        );
      })}
    </Paper>
  );
};

const AnalistaChat: React.FC = () => {
  const { enqueueSnackbar } = useSnackbar();
  const [messages, setMessages] = useState<Msg[]>([{
    role: 'bot', ts: Date.now(), intent: 'saludo',
    text: 'Hola, soy el analista de Kapitalya. Te respondo con los datos reales '
        + 'del negocio: ventas y ganancias, tasas, qué puede pasar con una divisa, '
        + 'contexto macro e inventario. ¿Qué quieres saber?',
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
      const res = await api.post('/analytics/assistant/', { message: q });
      const d: AssistantResponse = res.data;
      setMessages(m => [...m, { role: 'bot', text: d.reply, intent: d.intent, ts: Date.now() }]);
    } catch (e: any) {
      const msg = e?.response?.data?.error ?? 'El analista no está disponible';
      enqueueSnackbar(msg, { variant: 'error' });
      setMessages(m => [...m, { role: 'bot', ts: Date.now(),
        text: `No pude analizar eso ahora (${msg}). Intenta de nuevo.` }]);
    } finally {
      setBusy(false);
    }
  }, [busy, enqueueSnackbar]);

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, display: 'flex', flexDirection: 'column',
               height: 'calc(100vh - 120px)' }}>
      <Typography variant="h5" fontWeight={700} gutterBottom>Analista</Typography>
      <Alert severity="info" sx={{ mb: 2 }}>
        Respuestas calculadas sobre los datos vivos del sistema y sus modelos ML
        (que se reentrenan cada noche). Referencia operativa, no asesoría definitiva.
      </Alert>

      <Card variant="outlined" sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <CardContent sx={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          {messages.map((m, i) => (
            <Box key={i} sx={{ display: 'flex', gap: 1,
                               justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
              {m.role === 'bot' && <Insights color="primary" sx={{ mt: 0.5 }} />}
              {m.role === 'user' ? (
                <Paper sx={{ p: 1.5, maxWidth: '75%', bgcolor: 'primary.main', color: 'primary.contrastText' }}>
                  <Typography variant="body2">{m.text}</Typography>
                </Paper>
              ) : <BotBubble msg={m} />}
              {m.role === 'user' && <Person color="action" sx={{ mt: 0.5 }} />}
            </Box>
          ))}
          {busy && (
            <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
              <Insights color="primary" /><CircularProgress size={16} />
              <Typography variant="caption" color="text.secondary">consultando datos…</Typography>
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
            <TextField fullWidth size="small" placeholder="Pregúntame sobre el negocio, tasas, una divisa…"
                       value={input} onChange={e => setInput(e.target.value)}
                       onKeyDown={e => { if (e.key === 'Enter') ask(input); }} disabled={busy} />
            <IconButton color="primary" onClick={() => ask(input)} disabled={busy || !input.trim()}>
              <Send />
            </IconButton>
          </Box>
        </Box>
      </Card>
    </Box>
  );
};

export default AnalistaChat;
