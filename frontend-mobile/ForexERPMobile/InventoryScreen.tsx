import React, { useState, useEffect, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, RefreshControl,
  TouchableOpacity, ActivityIndicator,
} from 'react-native';
import { inventoryApi } from '../services/api';
import { CurrencyInventory } from '../types';

const FLAGS: Record<string, string> = { USD: '🇺🇸', EUR: '🇪🇺', BRL: '🇧🇷', ARS: '🇦🇷', BOB: '🇧🇴' };

function StockBar({ value, min, max }: { value: number; min: number; max: number }) {
  const pct = Math.min((value / max) * 100, 100);
  const color = value < min ? '#E74C3C' : value < min * 1.5 ? '#F39C12' : '#1F7A4D';
  return (
    <View style={barStyles.track}>
      <View style={[barStyles.fill, { width: `${pct}%` as any, backgroundColor: color }]} />
    </View>
  );
}

const barStyles = StyleSheet.create({
  track: { height: 8, backgroundColor: '#E8ECF0', borderRadius: 4, marginTop: 8, overflow: 'hidden' },
  fill: { height: '100%', borderRadius: 4 },
});

function InventoryCard({ item }: { item: CurrencyInventory }) {
  const pct = Math.min((item.total_balance / item.maximum_stock) * 100, 100);
  const status = item.needs_replenishment
    ? { label: 'CRÍTICO', color: '#E74C3C', bg: '#FDEDEC' }
    : pct < 50
    ? { label: 'BAJO', color: '#F39C12', bg: '#FEF9E7' }
    : { label: 'OK', color: '#1F7A4D', bg: '#EBF7EE' };

  return (
    <View style={styles.card}>
      <View style={styles.cardHeader}>
        <View style={styles.cardLeft}>
          <Text style={styles.flag}>{FLAGS[item.currency] ?? '🌐'}</Text>
          <Text style={styles.currency}>{item.currency}</Text>
        </View>
        <View style={[styles.statusBadge, { backgroundColor: status.bg }]}>
          <Text style={[styles.statusText, { color: status.color }]}>{status.label}</Text>
        </View>
      </View>

      <Text style={styles.balanceLabel}>Saldo Total</Text>
      <Text style={styles.balance}>
        {item.total_balance.toLocaleString('es-BO', { minimumFractionDigits: 2 })}
      </Text>

      <StockBar value={item.total_balance} min={item.minimum_stock} max={item.maximum_stock} />

      <View style={styles.detailsRow}>
        <View style={styles.detailItem}>
          <Text style={styles.detailLabel}>Físico</Text>
          <Text style={styles.detailValue}>
            {item.physical_balance.toLocaleString('es-BO', { minimumFractionDigits: 2 })}
          </Text>
        </View>
        <View style={styles.detailItem}>
          <Text style={styles.detailLabel}>Digital</Text>
          <Text style={styles.detailValue}>
            {item.digital_balance.toLocaleString('es-BO', { minimumFractionDigits: 2 })}
          </Text>
        </View>
        <View style={styles.detailItem}>
          <Text style={styles.detailLabel}>CPP</Text>
          <Text style={styles.detailValue}>{item.weighted_average_cost.toFixed(4)}</Text>
        </View>
      </View>

      <View style={styles.limitsRow}>
        <Text style={styles.limitText}>🔻 Mínimo: {item.minimum_stock.toLocaleString('es-BO')}</Text>
        <Text style={styles.limitText}>🔺 Máximo: {item.maximum_stock.toLocaleString('es-BO')}</Text>
      </View>

      {item.needs_replenishment && (
        <View style={styles.alertBanner}>
          <Text style={styles.alertText}>⚠️ Requiere reposición urgente</Text>
        </View>
      )}
    </View>
  );
}

export default function InventoryScreen() {
  const [inventory, setInventory] = useState<CurrencyInventory[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');

  const loadInventory = useCallback(async () => {
    try {
      setError('');
      const data = await inventoryApi.getAll();
      setInventory(data);
    } catch {
      setError('No se pudo cargar el inventario.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { loadInventory(); }, [loadInventory]);
  const onRefresh = () => { setRefreshing(true); loadInventory(); };

  const critical = inventory.filter(i => i.needs_replenishment);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#2E75B6" />
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#2E75B6" />}
    >
      <View style={styles.header}>
        <Text style={styles.headerTitle}>🏦 Control de Inventario</Text>
        <Text style={styles.headerSub}>{inventory.length} divisas registradas</Text>
      </View>

      {critical.length > 0 && (
        <View style={styles.criticalBanner}>
          <Text style={styles.criticalTitle}>🚨 {critical.length} divisa{critical.length > 1 ? 's' : ''} con stock crítico</Text>
          <Text style={styles.criticalSub}>{critical.map(i => i.currency).join(', ')}</Text>
        </View>
      )}

      {error ? (
        <TouchableOpacity style={styles.errorBanner} onPress={loadInventory}>
          <Text style={styles.errorText}>⚠️ {error} — Toca para reintentar</Text>
        </TouchableOpacity>
      ) : null}

      <View style={styles.body}>
        {inventory.length === 0
          ? <Text style={styles.emptyText}>No hay inventario registrado.</Text>
          : inventory.map(item => <InventoryCard key={item.id} item={item} />)
        }
      </View>
      <View style={{ height: 20 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F5F7FA' },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#F5F7FA' },
  header: { backgroundColor: '#1E3A5F', padding: 20, paddingTop: 52 },
  headerTitle: { color: '#FFF', fontSize: 20, fontWeight: '800' },
  headerSub: { color: '#7FAFD4', fontSize: 13, marginTop: 2 },
  criticalBanner: { backgroundColor: '#FDEDEC', borderLeftWidth: 5, borderLeftColor: '#E74C3C', margin: 16, borderRadius: 10, padding: 14 },
  criticalTitle: { color: '#C0392B', fontWeight: '800', fontSize: 14 },
  criticalSub: { color: '#C0392B', fontSize: 13, marginTop: 2 },
  errorBanner: { backgroundColor: '#FEF9E7', padding: 12, margin: 16, borderRadius: 10 },
  errorText: { color: '#F39C12', fontSize: 13 },
  body: { padding: 16 },
  emptyText: { textAlign: 'center', color: '#AAB4BE', marginTop: 40, fontSize: 15 },
  card: { backgroundColor: '#FFF', borderRadius: 16, padding: 16, marginBottom: 14, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.07, shadowRadius: 8, elevation: 3 },
  cardHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  cardLeft: { flexDirection: 'row', alignItems: 'center' },
  flag: { fontSize: 26, marginRight: 8 },
  currency: { fontSize: 20, fontWeight: '800', color: '#1E3A5F' },
  statusBadge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 20 },
  statusText: { fontWeight: '800', fontSize: 11 },
  balanceLabel: { fontSize: 11, color: '#999', fontWeight: '600' },
  balance: { fontSize: 26, fontWeight: '800', color: '#1E3A5F', marginTop: 2 },
  detailsRow: { flexDirection: 'row', marginTop: 14 },
  detailItem: { flex: 1, alignItems: 'center' },
  detailLabel: { fontSize: 10, color: '#999', fontWeight: '600' },
  detailValue: { fontSize: 13, fontWeight: '700', color: '#444', marginTop: 2 },
  limitsRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 10 },
  limitText: { fontSize: 11, color: '#AAB4BE' },
  alertBanner: { backgroundColor: '#FDEDEC', borderRadius: 8, padding: 10, marginTop: 10, alignItems: 'center' },
  alertText: { color: '#E74C3C', fontWeight: '700', fontSize: 13 },
});
