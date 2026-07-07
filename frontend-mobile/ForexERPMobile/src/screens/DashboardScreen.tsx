//  DashboardScreen.tsx - Pantalla principal del dashboard para la aplicación móvil Forex ERP
import React, {useState, useEffect, useCallback} from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { LineChart } from 'react-native-chart-kit';
import { Dimensions } from 'react-native';
import { ratesApi, predictionsApi, transactionsApi } from '../services/api';
import { RatesMap, Prediction, DailySummary } from '../types';
import { useAuth } from '../hooks/useAuth';

const { width: SCREEN_W } = Dimensions.get('window');
const CURRENCIES = ['USD', 'EUR', 'BRL', 'ARS'];
const REFRESH_MS = 60_000;

function RateCard({
  currency,
  rate,
}: {
  currency: string;
  rate: { buy: number; sell: number; spread: number };
}) {
  const flags: Record<string, string> = { USD: '🇺🇸', EUR: '🇪🇺', BRL: '🇧🇷', ARS: '🇦🇷' };
  return (
    <View style={styles.rateCard}>
      <Text style={styles.rateFlag}>{flags[currency] ?? '🌐'}</Text>
      <Text style={styles.rateCurrency}>{currency}</Text>
      <View style={styles.rateRow}>
        <View style={styles.rateCol}>
          <Text style={styles.rateLabel}>Compra</Text>
          <Text style={[styles.rateValue, { color: '#1F7A4D' }]}>{rate.buy.toFixed(4)}</Text>
        </View>
        <View style={styles.rateDivider} />
        <View style={styles.rateCol}>
          <Text style={styles.rateLabel}>Venta</Text>
          <Text style={[styles.rateValue, { color: '#C0392B' }]}>{rate.sell.toFixed(4)}</Text>
        </View>
      </View>
      <Text style={styles.spread}>Spread: {rate.spread.toFixed(4)}</Text>
    </View>
  );
}

function SummaryCard({ summary }: { summary: DailySummary }) {
  return (
    <View style={styles.summaryCard}>
      <Text style={styles.sectionTitle}>📅 Resumen del Día</Text>
      <View style={styles.summaryGrid}>
        <View style={styles.summaryItem}>
          <Text style={styles.summaryNum}>{summary.transaction_count}</Text>
          <Text style={styles.summaryLabel}>Transacciones</Text>
        </View>
        <View style={styles.summaryItem}>
          <Text style={[styles.summaryNum, { color: '#1F7A4D' }]}>
            Bs. {(summary.total_buy ?? 0).toLocaleString('es-BO', { minimumFractionDigits: 2 })}
          </Text>
          <Text style={styles.summaryLabel}>Total Compras</Text>
        </View>
        <View style={styles.summaryItem}>
          <Text style={[styles.summaryNum, { color: '#C0392B' }]}>
            Bs. {(summary.total_sell ?? 0).toLocaleString('es-BO', { minimumFractionDigits: 2 })}
          </Text>
          <Text style={styles.summaryLabel}>Total Ventas</Text>
        </View>
        <View style={[styles.summaryItem, styles.summaryHighlight]}>
          <Text style={[styles.summaryNum, { color: '#2E75B6' }]}>
            Bs. {(summary.total_profit ?? 0).toLocaleString('es-BO', { minimumFractionDigits: 2 })}
          </Text>
          <Text style={styles.summaryLabel}>Utilidad</Text>
        </View>
      </View>
    </View>
  );
}

export default function DashboardScreen() {
  const { user } = useAuth();
  const [rates, setRates] = useState<RatesMap>({});
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [summary, setSummary] = useState<DailySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');

  const loadData = useCallback(async () => {
    try {
      setError('');
      const [r, p, s] = await Promise.all([
        ratesApi.getCurrent(),
        predictionsApi.getCurrent('USD/BOB'),
        transactionsApi.getDailySummary(),
      ]);
      setRates(r);
      setPredictions(p.slice(0, 8));
      setSummary(s);
    } catch (e: any) {
      setError('No se pudo cargar los datos. Verifica tu conexión.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, REFRESH_MS);
    return () => clearInterval(interval);
  }, [loadData]);

  const onRefresh = () => { setRefreshing(true); loadData(); };

  const chartData = predictions.length > 0 ? {
    labels: predictions.map(p => new Date(p.prediction_date).getHours() + 'h'),
    datasets: [
      {
        data: predictions.map(p => p.predicted_sell_rate),
        color: (o = 1) => `rgba(46, 117, 182, ${o})`,
        strokeWidth: 2,
      },
      {
        data: predictions.map(p => p.predicted_buy_rate),
        color: (o = 1) => `rgba(31, 122, 77, ${o})`,
        strokeWidth: 2,
      },
    ],
    legend: ['Venta predicha', 'Compra predicha'],
  } : null;

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#2E75B6" />
        <Text style={styles.loadingText}>Cargando tasas...</Text>
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#2E75B6" />}
    >
      {/* Header */}
      <View style={styles.header}>
        <View>
          <Text style={styles.greeting}>Bienvenido 👋</Text>
          <Text style={styles.userName}>{user?.full_name ?? user?.username}</Text>
        </View>
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{user?.role}</Text>
        </View>
      </View>

      {error ? (
        <TouchableOpacity style={styles.errorBanner} onPress={loadData}>
          <Text style={styles.errorText}>⚠️ {error} — Toca para reintentar</Text>
        </TouchableOpacity>
      ) : null}

      {/* Tasas actuales */}
      <Text style={styles.sectionTitle}>💱 Tasas Actuales</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.ratesScroll}>
        {CURRENCIES.map(cur =>
          rates[cur] ? (
            <RateCard key={cur} currency={cur} rate={rates[cur]} />
          ) : null,
        )}
      </ScrollView>

      {/* Predicciones */}
      {chartData && (
        <View style={styles.chartCard}>
          <Text style={styles.sectionTitle}>🔮 Predicción USD/BOB (8h)</Text>
          <LineChart
            data={chartData}
            width={SCREEN_W - 40}
            height={180}
            chartConfig={{
              backgroundColor: '#FFFFFF',
              backgroundGradientFrom: '#FFFFFF',
              backgroundGradientTo: '#F5F7FA',
              decimalPlaces: 4,
              color: (o = 1) => `rgba(30, 58, 95, ${o})`,
              labelColor: (o = 1) => `rgba(85, 85, 85, ${o})`,
              propsForDots: { r: '3' },
            }}
            bezier
            style={{ borderRadius: 12 }}
          />
        </View>
      )}

      {/* Resumen del día */}
      {summary && <SummaryCard summary={summary} />}
      {summary && summary.transaction_count === 0 && (
        <View style={styles.emptyBanner}>
          <Text style={styles.emptyBannerText}>
            📋 Sin transacciones hoy. Registra la primera operación.
          </Text>
        </View>
      )}
      <View style={{ height: 20 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F5F7FA' },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#F5F7FA' },
  loadingText: { marginTop: 12, color: '#666', fontSize: 14 },
  header: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    backgroundColor: '#1E3A5F', padding: 20, paddingTop: 52,
  },
  greeting: { color: '#7FAFD4', fontSize: 13 },
  userName: { color: '#FFF', fontSize: 18, fontWeight: '700', marginTop: 2 },
  badge: { backgroundColor: '#2E75B6', paddingHorizontal: 12, paddingVertical: 6, borderRadius: 20 },
  badgeText: { color: '#FFF', fontSize: 11, fontWeight: '700' },
  errorBanner: { backgroundColor: '#FDEDEC', padding: 12, margin: 16, borderRadius: 10, borderLeftWidth: 4, borderLeftColor: '#E74C3C' },
  errorText: { color: '#C0392B', fontSize: 13 },
  sectionTitle: { fontSize: 16, fontWeight: '700', color: '#1E3A5F', marginHorizontal: 16, marginTop: 20, marginBottom: 10 },
  ratesScroll: { paddingLeft: 16 },
  rateCard: {
    backgroundColor: '#FFF', borderRadius: 16, padding: 16, marginRight: 12,
    width: 160, shadowColor: '#000', shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.07, shadowRadius: 8, elevation: 3,
  },
  rateFlag: { fontSize: 28, marginBottom: 4 },
  rateCurrency: { fontSize: 18, fontWeight: '800', color: '#1E3A5F', marginBottom: 10 },
  rateRow: { flexDirection: 'row', alignItems: 'center' },
  rateCol: { flex: 1, alignItems: 'center' },
  rateDivider: { width: 1, height: 32, backgroundColor: '#E0E8F0', marginHorizontal: 4 },
  rateLabel: { fontSize: 10, color: '#999', fontWeight: '600', marginBottom: 2 },
  rateValue: { fontSize: 14, fontWeight: '700' },
  spread: { fontSize: 10, color: '#AAB4BE', marginTop: 8, textAlign: 'center' },
  chartCard: { backgroundColor: '#FFF', margin: 16, borderRadius: 16, padding: 16, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.07, shadowRadius: 8, elevation: 3 },
  summaryCard: { backgroundColor: '#FFF', margin: 16, borderRadius: 16, padding: 16, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.07, shadowRadius: 8, elevation: 3 },
  summaryGrid: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 8 },
  summaryItem: { width: '50%', paddingVertical: 12, paddingHorizontal: 8 },
  summaryHighlight: { backgroundColor: '#EBF3FB', borderRadius: 10 },
  summaryNum: { fontSize: 15, fontWeight: '800', color: '#1E3A5F' },
  summaryLabel: { fontSize: 11, color: '#888', marginTop: 2 },
  emptyBanner: {
  backgroundColor: '#EBF3FB',
  margin: 16,
  borderRadius: 12,
  padding: 16,
  alignItems: 'center',
},
emptyBannerText: {
  color: '#2E75B6',
  fontWeight: '600',
  fontSize: 14,
  textAlign: 'center',
},
});
