import React, { useState, useEffect, useCallback } from 'react';
import {
  View, Text, StyleSheet, FlatList, RefreshControl,
  TouchableOpacity, ActivityIndicator,
} from 'react-native';
import { alertsApi } from '../services/api';
import { Alert as AlertType, AlertSeverity } from '../types';

const SEVERITY_CONFIG: Record<AlertSeverity, { color: string; bg: string; icon: string }> = {
  CRITICAL: { color: '#C0392B', bg: '#FDEDEC', icon: '🚨' },
  HIGH:     { color: '#E74C3C', bg: '#FDEDEC', icon: '⚠️' },
  MEDIUM:   { color: '#F39C12', bg: '#FEF9E7', icon: '🔔' },
  LOW:      { color: '#1F7A4D', bg: '#EBF7EE', icon: 'ℹ️' },
};

function AlertCard({
  alert,
  onMarkRead,
}: {
  alert: AlertType;
  onMarkRead: (id: number) => void;
}) {
  const cfg = SEVERITY_CONFIG[alert.severity] ?? SEVERITY_CONFIG.LOW;
  const date = new Date(alert.created_at);
  const timeStr = date.toLocaleTimeString('es-BO', { hour: '2-digit', minute: '2-digit' });
  const dateStr = date.toLocaleDateString('es-BO', { day: '2-digit', month: 'short' });

  return (
    <View style={[styles.card, alert.is_read && styles.cardRead]}>
      <View style={styles.cardTop}>
        <View style={[styles.iconBadge, { backgroundColor: cfg.bg }]}>
          <Text style={styles.iconText}>{cfg.icon}</Text>
        </View>
        <View style={styles.cardContent}>
          <View style={styles.cardTitleRow}>
            <Text style={[styles.cardTitle, alert.is_read && styles.cardTitleRead]}>
              {alert.title}
            </Text>
            <View style={[styles.severityBadge, { backgroundColor: cfg.bg }]}>
              <Text style={[styles.severityText, { color: cfg.color }]}>{alert.severity}</Text>
            </View>
          </View>
          <Text style={styles.cardMessage}>{alert.message}</Text>
          <View style={styles.cardMeta}>
            <Text style={styles.metaText}>💱 {alert.currency}</Text>
            <Text style={styles.metaText}>🕐 {dateStr} {timeStr}</Text>
          </View>
        </View>
      </View>
      {!alert.is_read && (
        <TouchableOpacity style={styles.readBtn} onPress={() => onMarkRead(alert.id)}>
          <Text style={styles.readBtnText}>Marcar como leída</Text>
        </TouchableOpacity>
      )}
    </View>
  );
}

export default function AlertsScreen() {
  const [alerts, setAlerts] = useState<AlertType[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<AlertSeverity | 'ALL'>('ALL');

  const loadAlerts = useCallback(async () => {
    try {
      const data = await alertsApi.getActive();
      setAlerts(data);
    } catch {
      // silencioso — pull to refresh disponible
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { loadAlerts(); }, [loadAlerts]);
  const onRefresh = () => { setRefreshing(true); loadAlerts(); };

  const handleMarkRead = async (id: number) => {
    try {
      await alertsApi.markRead(id);
      setAlerts(prev => prev.map(a => a.id === id ? { ...a, is_read: true } : a));
    } catch {
      // ignorar
    }
  };

  const filtered = filter === 'ALL' ? alerts : alerts.filter(a => a.severity === filter);
  const unread = alerts.filter(a => !a.is_read).length;

  if (loading) {
    return <View style={styles.center}><ActivityIndicator size="large" color="#2E75B6" /></View>;
  }

  return (
    <View style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <View>
          <Text style={styles.headerTitle}>🔔 Alertas</Text>
          {unread > 0 && (
            <Text style={styles.headerSub}>{unread} sin leer</Text>
          )}
        </View>
        {unread > 0 && (
          <View style={styles.unreadBadge}>
            <Text style={styles.unreadText}>{unread}</Text>
          </View>
        )}
      </View>

      {/* Filtros de severidad */}
      <View style={styles.filterRow}>
        {(['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const).map(s => (
          <TouchableOpacity
            key={s}
            style={[styles.filterBtn, filter === s && styles.filterBtnActive]}
            onPress={() => setFilter(s)}
          >
            <Text style={[styles.filterText, filter === s && styles.filterTextActive]}>
              {s === 'ALL' ? 'Todas' : s}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <FlatList
        data={filtered}
        keyExtractor={item => String(item.id)}
        renderItem={({ item }) => <AlertCard alert={item} onMarkRead={handleMarkRead} />}
        contentContainerStyle={styles.list}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#2E75B6" />}
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text style={styles.emptyIcon}>✅</Text>
            <Text style={styles.emptyText}>No hay alertas activas</Text>
          </View>
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F5F7FA' },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#F5F7FA' },
  header: { backgroundColor: '#1E3A5F', padding: 20, paddingTop: 52, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  headerTitle: { color: '#FFF', fontSize: 20, fontWeight: '800' },
  headerSub: { color: '#7FAFD4', fontSize: 13, marginTop: 2 },
  unreadBadge: { backgroundColor: '#E74C3C', width: 36, height: 36, borderRadius: 18, justifyContent: 'center', alignItems: 'center' },
  unreadText: { color: '#FFF', fontWeight: '800', fontSize: 15 },
  filterRow: { flexDirection: 'row', paddingHorizontal: 12, paddingVertical: 10, backgroundColor: '#FFF', borderBottomWidth: 1, borderBottomColor: '#E8ECF0' },
  filterBtn: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 16, marginRight: 6, backgroundColor: '#F5F7FA' },
  filterBtnActive: { backgroundColor: '#1E3A5F' },
  filterText: { fontSize: 11, fontWeight: '700', color: '#888' },
  filterTextActive: { color: '#FFF' },
  list: { padding: 16 },
  card: { backgroundColor: '#FFF', borderRadius: 14, padding: 14, marginBottom: 12, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.07, shadowRadius: 6, elevation: 3 },
  cardRead: { opacity: 0.6 },
  cardTop: { flexDirection: 'row' },
  iconBadge: { width: 44, height: 44, borderRadius: 22, justifyContent: 'center', alignItems: 'center', marginRight: 12 },
  iconText: { fontSize: 20 },
  cardContent: { flex: 1 },
  cardTitleRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 },
  cardTitle: { flex: 1, fontSize: 14, fontWeight: '800', color: '#1E3A5F', marginRight: 8 },
  cardTitleRead: { color: '#AAB4BE' },
  severityBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 10 },
  severityText: { fontSize: 10, fontWeight: '800' },
  cardMessage: { fontSize: 13, color: '#555', lineHeight: 18, marginBottom: 8 },
  cardMeta: { flexDirection: 'row', gap: 12 },
  metaText: { fontSize: 11, color: '#AAB4BE' },
  readBtn: { borderTopWidth: 1, borderTopColor: '#F0F4F8', marginTop: 10, paddingTop: 10, alignItems: 'flex-end' },
  readBtnText: { color: '#2E75B6', fontWeight: '700', fontSize: 13 },
  empty: { alignItems: 'center', paddingTop: 60 },
  emptyIcon: { fontSize: 52, marginBottom: 12 },
  emptyText: { color: '#AAB4BE', fontSize: 16, fontWeight: '600' },
});
