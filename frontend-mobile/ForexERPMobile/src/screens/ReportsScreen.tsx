import React, { useState, useEffect, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, RefreshControl,
  TouchableOpacity,
} from 'react-native';
import { reportsApi, transactionsApi } from '../services/api';
import { ReportSummary, DailySummary } from '../types';
import LoadingView from '../components/LoadingView';
import ErrorBanner from '../components/ErrorBanner';
import EmptyState from '../components/EmptyState';

const FLAGS: Record<string, string> = { USD: '🇺🇸', EUR: '🇪🇺', BRL: '🇧🇷', ARS: '🇦🇷' };

function CurrencyReportRow({ item }: { item: ReportSummary }) {
  const profitPositive = (item.profit ?? 0) >= 0;
  return (
    <View style={styles.reportRow}>
      <View style={styles.reportLeft}>
        <Text style={styles.reportFlag}>{FLAGS[item.currency] ?? '🌐'}</Text>
        <Text style={styles.reportCurrency}>{item.currency}</Text>
      </View>
      <View style={styles.reportCell}>
        <Text style={styles.reportLabel}>Compras</Text>
        <Text style={styles.reportValue}>{(item.total_buy ?? 0).toLocaleString('es-BO', { minimumFractionDigits: 2 })}</Text>
      </View>
      <View style={styles.reportCell}>
        <Text style={styles.reportLabel}>Ventas</Text>
        <Text style={styles.reportValue}>{(item.total_sell ?? 0).toLocaleString('es-BO', { minimumFractionDigits: 2 })}</Text>
      </View>
      <View style={styles.reportCell}>
        <Text style={styles.reportLabel}>Utilidad</Text>
        <Text style={[styles.reportValue, { color: profitPositive ? '#1F7A4D' : '#E74C3C' }]}>
          {profitPositive ? '+' : ''}{(item.profit ?? 0).toLocaleString('es-BO', { minimumFractionDigits: 2 })}
        </Text>
      </View>
    </View>
  );
}

function DateSelector({ date, onChange }: { date: Date; onChange: (d: Date) => void }) {
  const fmt = (d: Date) => d.toLocaleDateString('es-BO', { day: '2-digit', month: 'short', year: 'numeric' });
  const prev = () => { const d = new Date(date); d.setDate(d.getDate() - 1); onChange(d); };
  const next = () => {
    const d = new Date(date);
    d.setDate(d.getDate() + 1);
    if (d <= new Date()) onChange(d);
  };
  return (
    <View style={styles.datePicker}>
      <TouchableOpacity style={styles.dateBtn} onPress={prev}>
        <Text style={styles.dateBtnText}>‹</Text>
      </TouchableOpacity>
      <Text style={styles.dateLabel}>{fmt(date)}</Text>
      <TouchableOpacity
        style={[styles.dateBtn, date.toDateString() === new Date().toDateString() && styles.dateBtnDisabled]}
        onPress={next}
        disabled={date.toDateString() === new Date().toDateString()}
      >
        <Text style={styles.dateBtnText}>›</Text>
      </TouchableOpacity>
    </View>
  );
}

export default function ReportsScreen() {
  const [date, setDate] = useState(new Date());
  const [report, setReport] = useState<ReportSummary[]>([]);
  const [summary, setSummary] = useState<DailySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dateStr = date.toISOString().split('T')[0];

  const loadReport = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [r, s] = await Promise.all([
        reportsApi.getDaily(dateStr),
        transactionsApi.getDailySummary(dateStr),
      ]);
      setReport(r);
      setSummary(s);
    } catch {
      setReport([]);
      setError('No se pudieron cargar los reportes. Verifica tu conexión.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [dateStr]);

  useEffect(() => { loadReport(); }, [loadReport]);
  const onRefresh = () => { setRefreshing(true); loadReport(); };

  const totalProfit = report.reduce((acc, r) => acc + (r.profit ?? 0), 0);

  return (
    <ScrollView
      style={styles.container}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#2E75B6" />}
    >
      <View style={styles.header}>
        <Text style={styles.headerTitle}>📈 Reportes</Text>
      </View>

      <DateSelector date={date} onChange={setDate} />

      {loading ? (
        <LoadingView text="Cargando reportes…" />
      ) : error ? (
        <ErrorBanner message={error} onRetry={loadReport} />
      ) : (
        <>
          {/* KPIs */}
          {summary && (
            <View style={styles.kpiRow}>
              <View style={styles.kpiCard}>
                <Text style={styles.kpiValue}>{summary.transaction_count}</Text>
                <Text style={styles.kpiLabel}>Transacciones</Text>
              </View>
              <View style={[styles.kpiCard, { backgroundColor: '#EBF7EE' }]}>
                <Text style={[styles.kpiValue, { color: '#1F7A4D' }]}>
                  Bs. {(summary.total_buy ?? 0).toLocaleString('es-BO', { minimumFractionDigits: 0 })}
                </Text>
                <Text style={styles.kpiLabel}>Total Compras</Text>
              </View>
              <View style={[styles.kpiCard, { backgroundColor: '#FDEDEC' }]}>
                <Text style={[styles.kpiValue, { color: '#C0392B' }]}>
                  Bs. {(summary.total_sell ?? 0).toLocaleString('es-BO', { minimumFractionDigits: 0 })}
                </Text>
                <Text style={styles.kpiLabel}>Total Ventas</Text>
              </View>
            </View>
          )}

          {/* Utilidad total */}
          <View style={styles.profitBanner}>
            <Text style={styles.profitLabel}>Utilidad Total del Día</Text>
            <Text style={[styles.profitValue, { color: totalProfit >= 0 ? '#1F7A4D' : '#E74C3C' }]}>
              Bs. {totalProfit.toLocaleString('es-BO', { minimumFractionDigits: 2 })}
            </Text>
          </View>

          {/* Detalle por divisa */}
          <View style={styles.tableCard}>
            <Text style={styles.sectionTitle}>Detalle por Divisa</Text>
            {report.length === 0 ? (
              <EmptyState icon="🗓️" text="Sin operaciones para esta fecha." />
            ) : (
              report.map(item => <CurrencyReportRow key={item.currency} item={item} />)
            )}
          </View>
        </>
      )}
      <View style={{ height: 20 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F5F7FA' },
  header: { backgroundColor: '#1E3A5F', padding: 20, paddingTop: 52 },
  headerTitle: { color: '#FFF', fontSize: 20, fontWeight: '800' },
  datePicker: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFF', paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: '#E8ECF0' },
  dateBtn: { paddingHorizontal: 20, paddingVertical: 8 },
  dateBtnDisabled: { opacity: 0.3 },
  dateBtnText: { fontSize: 24, color: '#2E75B6', fontWeight: '700' },
  dateLabel: { fontSize: 16, fontWeight: '700', color: '#1E3A5F', minWidth: 160, textAlign: 'center' },
  kpiRow: { flexDirection: 'row', padding: 16, gap: 8 },
  kpiCard: { flex: 1, backgroundColor: '#FFF', borderRadius: 12, padding: 12, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.06, shadowRadius: 6, elevation: 2 },
  kpiValue: { fontSize: 15, fontWeight: '800', color: '#1E3A5F' },
  kpiLabel: { fontSize: 10, color: '#888', marginTop: 2, fontWeight: '600' },
  profitBanner: { backgroundColor: '#1E3A5F', margin: 16, borderRadius: 16, padding: 20, alignItems: 'center' },
  profitLabel: { color: '#7FAFD4', fontSize: 13, fontWeight: '600' },
  profitValue: { fontSize: 32, fontWeight: '800', marginTop: 4 },
  tableCard: { backgroundColor: '#FFF', margin: 16, borderRadius: 16, padding: 16, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.07, shadowRadius: 8, elevation: 3 },
  sectionTitle: { fontSize: 15, fontWeight: '800', color: '#1E3A5F', marginBottom: 14 },
  reportRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: '#F0F4F8' },
  reportLeft: { flexDirection: 'row', alignItems: 'center', width: 60 },
  reportFlag: { fontSize: 18, marginRight: 4 },
  reportCurrency: { fontSize: 14, fontWeight: '800', color: '#1E3A5F' },
  reportCell: { flex: 1, alignItems: 'center' },
  reportLabel: { fontSize: 9, color: '#AAB4BE', fontWeight: '700' },
  reportValue: { fontSize: 12, fontWeight: '700', color: '#333', marginTop: 2 },
});
