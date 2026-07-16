// MacroScreen.tsx — Panel Macroeconómico de Bolivia (datos REALES)
//
// Réplica móvil de frontend-web MacroPanel.tsx. Fuentes (backend /api/macro/):
// World Bank (inflación, reservas, PIB, deuda, tasa, TC oficial), open.er-api
// (USD internacional diario) y brecha oficial↔paralelo de las tasas propias.
// Endpoints: /macro/indicators/summary/, /macro/indicators/series/?series=X,
// /macro/news/pulse/ (índice de sentimiento + titulares).
import React, { useCallback, useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
  Dimensions,
} from 'react-native';
import { LineChart } from 'react-native-chart-kit';
import { macroApi } from '../services/api';
import { MacroIndicatorSummary, MacroSeriesPoint, NewsPulse } from '../types';

const { width: SCREEN_W } = Dimensions.get('window');

// Metadatos de presentación por serie (ícono + formateo del valor).
const CARD_META: Record<string, { icon: string; fmt: (v: number) => string }> = {
  inflacion_yoy:       { icon: '📈', fmt: v => `${v.toFixed(1)}%` },
  reservas_usd:        { icon: '💰', fmt: v => `$${(v / 1e6).toFixed(0)}M` },
  pib_crecimiento:     { icon: '📊', fmt: v => `${v.toFixed(1)}%` },
  deuda_externa_usd:   { icon: '🏛️', fmt: v => `$${(v / 1e9).toFixed(1)}B` },
  tasa_interes_activa: { icon: '％', fmt: v => `${v.toFixed(1)}%` },
  tc_oficial_promedio: { icon: '🌐', fmt: v => `Bs ${v.toFixed(2)}` },
  usd_internacional:   { icon: '🔁', fmt: v => `Bs ${v.toFixed(3)}` },
  tc_oficial_diario:   { icon: '🏦', fmt: v => `Bs ${v.toFixed(2)}` },
  brecha_oficial_pct:  { icon: '↔️', fmt: v => `${v.toFixed(2)}%` },
};

const PULSE_META: Record<string, { color: string; bg: string; icon: string }> = {
  alcista: { color: '#1F7A4D', bg: '#E7F5EE', icon: '📈' },
  bajista: { color: '#C0392B', bg: '#FDEDEC', icon: '📉' },
  neutral: { color: '#5A6672', bg: '#EEF1F5', icon: '➖' },
};

function IndicatorCard({
  ind,
  selected,
  onPress,
}: {
  ind: MacroIndicatorSummary;
  selected: boolean;
  onPress: () => void;
}) {
  const meta = CARD_META[ind.series];
  const value = parseFloat(ind.value);
  const stale = ind.age_days > 400;
  return (
    <TouchableOpacity
      style={[styles.card, selected && styles.cardSelected]}
      onPress={onPress}
      activeOpacity={0.8}
    >
      <View style={styles.cardHead}>
        <Text style={styles.cardIcon}>{meta?.icon ?? '📌'}</Text>
        <Text style={styles.cardLabel} numberOfLines={2}>
          {ind.series_label}
        </Text>
      </View>
      <Text style={styles.cardValue}>
        {meta && !isNaN(value) ? meta.fmt(value) : ind.value}
      </Text>
      <View style={styles.cardTags}>
        <View style={styles.tag}>
          <Text style={styles.tagText}>{ind.date}</Text>
        </View>
        <View style={[styles.tag, stale ? styles.tagWarn : styles.tagOk]}>
          <Text style={[styles.tagText, stale ? styles.tagWarnText : styles.tagOkText]}>
            {ind.age_days === 0 ? 'hoy' : `hace ${ind.age_days}d`}
          </Text>
        </View>
      </View>
    </TouchableOpacity>
  );
}

export default function MacroScreen() {
  const [summary, setSummary] = useState<MacroIndicatorSummary[]>([]);
  const [selected, setSelected] = useState('inflacion_yoy');
  const [points, setPoints] = useState<MacroSeriesPoint[]>([]);
  const [pulse, setPulse] = useState<NewsPulse | null>(null);
  const [loading, setLoading] = useState(true);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');

  const loadSummary = useCallback(async () => {
    try {
      setError('');
      const [ind, p] = await Promise.all([
        macroApi.getSummary(),
        macroApi.getNewsPulse().catch(() => null),
      ]);
      setSummary(ind);
      setPulse(p);
      // Si la serie seleccionada ya no existe, cae en la primera disponible.
      if (ind.length && !ind.some(s => s.series === selected)) {
        setSelected(ind[0].series);
      }
    } catch {
      setError('No se pudieron cargar los indicadores macro.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [selected]);

  const loadSeries = useCallback(async (series: string) => {
    setSeriesLoading(true);
    try {
      setPoints(await macroApi.getSeries(series));
    } catch {
      setPoints([]);
    } finally {
      setSeriesLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  useEffect(() => {
    loadSeries(selected);
  }, [selected, loadSeries]);

  const onRefresh = () => {
    setRefreshing(true);
    loadSummary();
    loadSeries(selected);
  };

  const selectedMeta = summary.find(s => s.series === selected);

  // Serie -> datos del LineChart, adelgazando etiquetas para que no se amontonen.
  const nums = points.map(p => parseFloat(p.value)).filter(v => !isNaN(v));
  const step = Math.max(1, Math.ceil(points.length / 6));
  const chartData =
    nums.length > 1
      ? {
          labels: points.map((p, i) =>
            i % step === 0 ? (p.date ?? '').slice(2, 7) : '',
          ),
          datasets: [
            { data: nums, color: (o = 1) => `rgba(46, 117, 182, ${o})`, strokeWidth: 2 },
          ],
        }
      : null;

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#2E75B6" />
        <Text style={styles.loadingText}>Cargando indicadores…</Text>
      </View>
    );
  }

  const pm = pulse?.label ? PULSE_META[pulse.label] ?? PULSE_META.neutral : null;

  return (
    <ScrollView
      style={styles.container}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#2E75B6" />
      }
    >
      <View style={styles.header}>
        <Text style={styles.headerTitle}>🌎 Macro Bolivia</Text>
        <Text style={styles.headerSubtitle}>
          Indicadores reales (World Bank · er-api · tasas propias). La brecha y el
          USD internacional se actualizan a diario.
        </Text>
      </View>

      {error ? (
        <TouchableOpacity style={styles.errorBanner} onPress={onRefresh}>
          <Text style={styles.errorText}>⚠️ {error} — Toca para reintentar</Text>
        </TouchableOpacity>
      ) : null}

      {/* Pulso de noticias */}
      {pulse && pm && (
        <View style={styles.pulseCard}>
          <View style={styles.pulseHead}>
            <Text style={styles.sectionTitleInline}>📰 Pulso de Noticias</Text>
            <View style={[styles.pulseChip, { backgroundColor: pm.bg }]}>
              <Text style={[styles.pulseChipText, { color: pm.color }]}>
                {pm.icon} {pulse.label}
                {pulse.index != null ? ` ${pulse.index > 0 ? '+' : ''}${pulse.index.toFixed(2)}` : ''}
              </Text>
            </View>
          </View>
          <Text style={styles.pulseMeta}>{pulse.noticias_48h} noticias con señal (48h)</Text>
          {pulse.alcistas.slice(0, 3).map((n, i) => (
            <Text key={`a${i}`} style={styles.newsUp} numberOfLines={2}>
              ▲ {n.title}
            </Text>
          ))}
          {pulse.bajistas.slice(0, 3).map((n, i) => (
            <Text key={`b${i}`} style={styles.newsDown} numberOfLines={2}>
              ▼ {n.title}
            </Text>
          ))}
        </View>
      )}

      {/* Tarjetas de indicadores */}
      {summary.length === 0 ? (
        <View style={styles.emptyBanner}>
          <Text style={styles.emptyBannerText}>
            Sin indicadores cargados. Ejecuta `python manage.py fetch_macro` en el backend.
          </Text>
        </View>
      ) : (
        <View style={styles.grid}>
          {summary.map(ind => (
            <IndicatorCard
              key={ind.series}
              ind={ind}
              selected={ind.series === selected}
              onPress={() => setSelected(ind.series)}
            />
          ))}
        </View>
      )}

      {/* Serie seleccionada */}
      {summary.length > 0 && (
        <View style={styles.chartCard}>
          <Text style={styles.sectionTitleInline}>
            {selectedMeta?.series_label ?? selected}
          </Text>
          {seriesLoading ? (
            <View style={styles.chartLoading}>
              <ActivityIndicator color="#2E75B6" />
            </View>
          ) : chartData ? (
            <LineChart
              data={chartData}
              width={SCREEN_W - 48}
              height={220}
              chartConfig={{
                backgroundColor: '#FFFFFF',
                backgroundGradientFrom: '#FFFFFF',
                backgroundGradientTo: '#F5F7FA',
                decimalPlaces: 2,
                color: (o = 1) => `rgba(30, 58, 95, ${o})`,
                labelColor: (o = 1) => `rgba(85, 85, 85, ${o})`,
                propsForDots: { r: '2' },
              }}
              bezier
              style={{ borderRadius: 12, marginTop: 8 }}
            />
          ) : (
            <Text style={styles.emptySeries}>Serie sin datos aún.</Text>
          )}
          {selectedMeta && (
            <Text style={styles.sourceText}>Fuente: {selectedMeta.source}</Text>
          )}
        </View>
      )}

      <View style={{ height: 24 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F5F7FA' },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#F5F7FA' },
  loadingText: { marginTop: 12, color: '#666', fontSize: 14 },

  header: { backgroundColor: '#1E3A5F', padding: 20, paddingTop: 52 },
  headerTitle: { color: '#FFF', fontSize: 18, fontWeight: '700' },
  headerSubtitle: { color: '#7FAFD4', fontSize: 12, marginTop: 4, lineHeight: 16 },

  errorBanner: { backgroundColor: '#FDEDEC', padding: 12, margin: 16, borderRadius: 10, borderLeftWidth: 4, borderLeftColor: '#E74C3C' },
  errorText: { color: '#C0392B', fontSize: 13 },

  sectionTitleInline: { fontSize: 15, fontWeight: '700', color: '#1E3A5F' },

  pulseCard: {
    backgroundColor: '#FFF', margin: 16, marginBottom: 8, borderRadius: 16, padding: 16,
    shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.07, shadowRadius: 8, elevation: 3,
  },
  pulseHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap' },
  pulseChip: { paddingVertical: 4, paddingHorizontal: 10, borderRadius: 14 },
  pulseChipText: { fontSize: 12, fontWeight: '800' },
  pulseMeta: { fontSize: 11, color: '#888', marginTop: 6, marginBottom: 6 },
  newsUp: { fontSize: 12, color: '#1F7A4D', marginTop: 4, lineHeight: 16 },
  newsDown: { fontSize: 12, color: '#C0392B', marginTop: 4, lineHeight: 16 },

  grid: { flexDirection: 'row', flexWrap: 'wrap', paddingHorizontal: 10, marginTop: 8 },
  card: {
    width: '46%', margin: '2%', backgroundColor: '#FFF', borderRadius: 14, padding: 12,
    borderWidth: 1, borderColor: '#FFF',
    shadowColor: '#000', shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.06, shadowRadius: 6, elevation: 2,
  },
  cardSelected: { borderColor: '#2E75B6', backgroundColor: '#F4F9FF' },
  cardHead: { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 6 },
  cardIcon: { fontSize: 16, marginRight: 6 },
  cardLabel: { flex: 1, fontSize: 11, color: '#7A8896', fontWeight: '600' },
  cardValue: { fontSize: 18, fontWeight: '800', color: '#1E3A5F' },
  cardTags: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 8 },
  tag: { backgroundColor: '#EEF1F5', borderRadius: 8, paddingVertical: 2, paddingHorizontal: 6, marginRight: 5, marginTop: 4 },
  tagText: { fontSize: 9, color: '#5A6672', fontWeight: '600' },
  tagOk: { backgroundColor: '#E7F5EE' },
  tagOkText: { color: '#1F7A4D' },
  tagWarn: { backgroundColor: '#FBF3E0' },
  tagWarnText: { color: '#B7791F' },

  chartCard: {
    backgroundColor: '#FFF', margin: 16, borderRadius: 16, padding: 16,
    shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.07, shadowRadius: 8, elevation: 3,
  },
  chartLoading: { height: 220, justifyContent: 'center', alignItems: 'center' },
  emptySeries: { color: '#8A94A0', fontSize: 13, paddingVertical: 24, textAlign: 'center' },
  sourceText: { fontSize: 10, color: '#AAB4BE', marginTop: 8 },

  emptyBanner: { backgroundColor: '#EBF3FB', margin: 16, borderRadius: 12, padding: 16, alignItems: 'center' },
  emptyBannerText: { color: '#2E75B6', fontWeight: '600', fontSize: 13, textAlign: 'center' },
});
