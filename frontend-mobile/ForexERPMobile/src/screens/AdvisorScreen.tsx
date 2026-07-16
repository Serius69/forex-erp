// AdvisorScreen.tsx — Asesor de Divisas (chat "¿compro o no?")
//
// Réplica móvil de frontend-web AdvisorChat.tsx. Compone las señales REALES del
// sistema (pronóstico ML, brecha oficial BCB↔paralelo, sentimiento de noticias,
// Monte Carlo, posición de inventario y AI pricing) en una recomendación
// COMPRAR/ESPERAR/VENDER. Backend determinista: POST /api/predictions/advisor/.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { advisorApi } from '../services/api';
import { AdvisorResponse } from '../types';

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

const DECISION_META: Record<string, { color: string; bg: string; icon: string }> = {
  COMPRAR: { color: '#1F7A4D', bg: '#E7F5EE', icon: '📈' },
  ESPERAR: { color: '#B7791F', bg: '#FBF3E0', icon: '⏸️' },
  VENDER:  { color: '#C0392B', bg: '#FDEDEC', icon: '📉' },
};

// Construye las viñetas de señales a partir del objeto heterogéneo `signals`,
// leyendo cada campo de forma defensiva (pueden faltar o venir como string).
function signalChips(signals: Record<string, any> | undefined): string[] {
  if (!signals) return [];
  const chips: string[] = [];
  const num = (v: any) => Number(v ?? 0);

  const f = signals.forecast;
  if (f) chips.push(`📊 ML ${num(f.delta_pct) > 0 ? '+' : ''}${f.delta_pct}% 24h`);

  const s = signals.sentimiento;
  if (s) chips.push(`📰 Noticias ${num(s.index) > 0 ? '+' : ''}${num(s.index).toFixed(2)}`);

  const b = signals.brecha;
  if (b) chips.push(`🏛️ Brecha BCB ${b.brecha_pct}%`);

  const m = signals.montecarlo;
  if (m && m.prob_sube_7d != null) {
    chips.push(`🎲 P(sube 7d) ${(num(m.prob_sube_7d) * 100).toFixed(0)}%`);
  }

  const p = signals.posicion;
  if (p?.stock) {
    chips.push(
      `📦 Stock ${num(p.stock).toLocaleString('es-BO')}` +
        (p.stock_pct_max ? ` (${p.stock_pct_max}%)` : ''),
    );
  }
  return chips;
}

function BotBubble({ msg }: { msg: Msg }) {
  const d = msg.data;
  const meta = d ? DECISION_META[d.decision] : null;
  const lines = msg.text.split('\n').filter(Boolean);
  const chips = signalChips(d?.signals);

  return (
    <View style={styles.botBubble}>
      {d && meta && (
        <View style={styles.decisionRow}>
          <View style={[styles.decisionChip, { backgroundColor: meta.bg }]}>
            <Text style={[styles.decisionChipText, { color: meta.color }]}>
              {meta.icon} {d.decision} {d.currency}
            </Text>
          </View>
          <Text style={styles.decisionMeta}>
            confianza {(d.confidence * 100).toFixed(0)}% · score{' '}
            {d.score > 0 ? '+' : ''}
            {d.score}
          </Text>
        </View>
      )}
      {lines.map((ln, i) => {
        const italic = ln.startsWith('_');
        const clean = ln.replace(/\*\*/g, '').replace(/^_|_$/g, '');
        return (
          <Text
            key={i}
            style={[styles.botLine, italic ? styles.botLineFootnote : null]}
          >
            {clean}
          </Text>
        );
      })}
      {chips.length > 0 && (
        <View style={styles.chipsWrap}>
          {chips.map((c, i) => (
            <View key={i} style={styles.signalChip}>
              <Text style={styles.signalChipText}>{c}</Text>
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

export default function AdvisorScreen() {
  const [messages, setMessages] = useState<Msg[]>([
    {
      role: 'bot',
      ts: Date.now(),
      text:
        'Hola — soy el asesor de divisas de Kapitalya. Pregúntame si conviene ' +
        'comprar o vender una divisa y te respondo con las señales reales del ' +
        'sistema: pronóstico ML, brecha oficial BCB, noticias, simulación y tu ' +
        'inventario.',
    },
  ]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<ScrollView>(null);

  useEffect(() => {
    // Autoscroll al final cuando llega/actualiza un mensaje.
    const t = setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 80);
    return () => clearTimeout(t);
  }, [messages, busy]);

  const ask = useCallback(
    async (text: string) => {
      const q = text.trim();
      if (!q || busy) return;
      setMessages(m => [...m, { role: 'user', text: q, ts: Date.now() }]);
      setInput('');
      setBusy(true);
      try {
        const d = await advisorApi.ask(q);
        setMessages(m => [...m, { role: 'bot', text: d.reply, data: d, ts: Date.now() }]);
      } catch (e: any) {
        const err = e?.message ?? 'El asesor no está disponible';
        setMessages(m => [
          ...m,
          {
            role: 'bot',
            ts: Date.now(),
            text: `No pude analizar eso ahora (${err}). Intenta de nuevo en un momento.`,
          },
        ]);
      } finally {
        setBusy(false);
      }
    },
    [busy],
  );

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
    >
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>🤖 Asesor de Divisas</Text>
        <Text style={styles.headerSubtitle}>
          Lectura estadística de señales reales — referencia operativa, no
          asesoría financiera definitiva.
        </Text>
      </View>

      {/* Conversación */}
      <ScrollView
        ref={scrollRef}
        style={styles.chat}
        contentContainerStyle={styles.chatContent}
      >
        {messages.map((m, i) => (
          <View
            key={i}
            style={[
              styles.msgRow,
              m.role === 'user' ? styles.msgRowUser : styles.msgRowBot,
            ]}
          >
            {m.role === 'user' ? (
              <View style={styles.userBubble}>
                <Text style={styles.userText}>{m.text}</Text>
              </View>
            ) : (
              <BotBubble msg={m} />
            )}
          </View>
        ))}
        {busy && (
          <View style={styles.typingRow}>
            <ActivityIndicator size="small" color="#2E75B6" />
            <Text style={styles.typingText}>analizando señales…</Text>
          </View>
        )}
      </ScrollView>

      {/* Sugerencias rápidas */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.quickBar}
        contentContainerStyle={styles.quickBarContent}
      >
        {QUICK.map(q => (
          <TouchableOpacity
            key={q}
            style={styles.quickChip}
            onPress={() => ask(q)}
            disabled={busy}
          >
            <Text style={styles.quickChipText}>{q}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {/* Entrada */}
      <View style={styles.inputBar}>
        <TextInput
          style={styles.input}
          placeholder="¿Compro dólares hoy?"
          placeholderTextColor="#9AA5B1"
          value={input}
          onChangeText={setInput}
          editable={!busy}
          returnKeyType="send"
          onSubmitEditing={() => ask(input)}
          maxLength={500}
        />
        <TouchableOpacity
          style={[styles.sendBtn, (busy || !input.trim()) && styles.sendBtnOff]}
          onPress={() => ask(input)}
          disabled={busy || !input.trim()}
        >
          <Text style={styles.sendBtnText}>➤</Text>
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F5F7FA' },
  header: { backgroundColor: '#1E3A5F', padding: 20, paddingTop: 52 },
  headerTitle: { color: '#FFF', fontSize: 18, fontWeight: '700' },
  headerSubtitle: { color: '#7FAFD4', fontSize: 12, marginTop: 4, lineHeight: 16 },

  chat: { flex: 1 },
  chatContent: { padding: 16, paddingBottom: 8 },

  msgRow: { marginBottom: 12, flexDirection: 'row' },
  msgRowUser: { justifyContent: 'flex-end' },
  msgRowBot: { justifyContent: 'flex-start' },

  userBubble: {
    backgroundColor: '#2E75B6',
    borderRadius: 16,
    borderBottomRightRadius: 4,
    paddingVertical: 10,
    paddingHorizontal: 14,
    maxWidth: '80%',
  },
  userText: { color: '#FFF', fontSize: 14 },

  botBubble: {
    backgroundColor: '#FFF',
    borderRadius: 16,
    borderBottomLeftRadius: 4,
    padding: 14,
    maxWidth: '88%',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 6,
    elevation: 2,
  },
  decisionRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 },
  decisionChip: { paddingVertical: 4, paddingHorizontal: 10, borderRadius: 14, marginRight: 8 },
  decisionChipText: { fontSize: 13, fontWeight: '800' },
  decisionMeta: { fontSize: 11, color: '#888' },

  botLine: { fontSize: 14, color: '#2C3E50', marginBottom: 4, lineHeight: 19 },
  botLineFootnote: { fontSize: 11, color: '#8A94A0', fontStyle: 'italic' },

  chipsWrap: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 6 },
  signalChip: {
    borderWidth: 1,
    borderColor: '#D6DEE7',
    borderRadius: 12,
    paddingVertical: 4,
    paddingHorizontal: 8,
    marginRight: 6,
    marginTop: 6,
    backgroundColor: '#F8FAFC',
  },
  signalChipText: { fontSize: 11, color: '#42556B', fontWeight: '600' },

  typingRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 6, paddingLeft: 4 },
  typingText: { marginLeft: 8, fontSize: 12, color: '#888' },

  quickBar: { maxHeight: 46, backgroundColor: '#F5F7FA' },
  quickBarContent: { paddingHorizontal: 12, alignItems: 'center' },
  quickChip: {
    borderWidth: 1,
    borderColor: '#2E75B6',
    borderRadius: 16,
    paddingVertical: 6,
    paddingHorizontal: 12,
    marginRight: 8,
    backgroundColor: '#EBF3FB',
  },
  quickChipText: { fontSize: 12, color: '#2E75B6', fontWeight: '600' },

  inputBar: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 10,
    backgroundColor: '#FFF',
    borderTopWidth: 1,
    borderTopColor: '#E8ECF0',
  },
  input: {
    flex: 1,
    backgroundColor: '#F1F4F8',
    borderRadius: 22,
    paddingHorizontal: 16,
    paddingVertical: Platform.OS === 'ios' ? 12 : 8,
    fontSize: 14,
    color: '#2C3E50',
  },
  sendBtn: {
    marginLeft: 8,
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#2E75B6',
    justifyContent: 'center',
    alignItems: 'center',
  },
  sendBtnOff: { backgroundColor: '#B7C4D2' },
  sendBtnText: { color: '#FFF', fontSize: 18, fontWeight: '700' },
});
