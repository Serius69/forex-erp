// src/screens/TarjetasScreen.tsx
import React, { useState, useEffect, useCallback } from 'react';
import {
  View, Text, ScrollView, TouchableOpacity, StyleSheet,
  RefreshControl, ActivityIndicator, Alert, Modal, TextInput,
  FlatList,
} from 'react-native';
import { tarjetasApi } from '../services/api';

const OPERADORA_COLOR: Record<string, string> = {
  TIGO: '#00A8E0', VIVA: '#E50914', CLARO: '#DA291C', ENTEL: '#FFB300',
};

interface TipoTarjeta {
  id: number;
  operadora: string;
  nombre: string;
  denominacion: number;
  stock_actual: number;
  costo_promedio: string;
  valor_inventario_bob: string;
}

interface VentaForm {
  tipo: TipoTarjeta | null;
  cantidad: string;
  precio_venta: string;
  medio_pago: string;
  cliente_nombre: string;
}

function TipoCard({ tipo, onVender }: { tipo: TipoTarjeta; onVender: () => void }) {
  const color = OPERADORA_COLOR[tipo.operadora] ?? '#607d8b';
  const stockLow = tipo.stock_actual < 20;

  return (
    <View style={[styles.card, { borderTopColor: color, borderTopWidth: 4 }]}>
      <View style={styles.cardHeader}>
        <View style={[styles.operadoraBadge, { backgroundColor: color }]}>
          <Text style={styles.operadoraText}>{tipo.operadora}</Text>
        </View>
        <Text style={[styles.stockNum, { color: stockLow ? '#C0392B' : '#1E3A5F' }]}>
          {tipo.stock_actual} uds.
        </Text>
      </View>
      <Text style={styles.tipoNombre}>{tipo.nombre}</Text>
      <Text style={styles.tipoDenom}>Bs. {tipo.denominacion?.toFixed(2)} c/u</Text>
      <View style={styles.cardRow}>
        <View>
          <Text style={styles.metaLabel}>Costo prom.</Text>
          <Text style={styles.metaVal}>Bs. {parseFloat(tipo.costo_promedio || '0').toFixed(2)}</Text>
        </View>
        <View style={{ alignItems: 'flex-end' }}>
          <Text style={styles.metaLabel}>Valor inv.</Text>
          <Text style={[styles.metaVal, { color: '#1976d2' }]}>
            Bs. {parseFloat(tipo.valor_inventario_bob || '0').toFixed(2)}
          </Text>
        </View>
      </View>
      {stockLow && (
        <View style={styles.lowStockBanner}>
          <Text style={styles.lowStockText}>⚠️ Stock bajo</Text>
        </View>
      )}
      <TouchableOpacity
        style={[styles.venderBtn, tipo.stock_actual === 0 && styles.venderBtnDisabled]}
        onPress={onVender}
        disabled={tipo.stock_actual === 0}
      >
        <Text style={styles.venderBtnText}>
          {tipo.stock_actual === 0 ? 'Sin stock' : '💰 Vender'}
        </Text>
      </TouchableOpacity>
    </View>
  );
}

export default function TarjetasScreen() {
  const [tipos, setTipos] = useState<TipoTarjeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [ventaModal, setVentaModal] = useState(false);
  const [form, setForm] = useState<VentaForm>({
    tipo: null, cantidad: '1', precio_venta: '', medio_pago: 'CASH', cliente_nombre: '',
  });
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await tarjetasApi.getInventario();
      setTipos(data);
    } catch {
      Alert.alert('Error', 'No se pudo cargar el inventario de tarjetas.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onRefresh = () => { setRefreshing(true); load(); };

  const openVenta = (tipo: TipoTarjeta) => {
    setForm({
      tipo,
      cantidad: '1',
      precio_venta: tipo.denominacion?.toString() ?? '',
      medio_pago: 'CASH',
      cliente_nombre: '',
    });
    setVentaModal(true);
  };

  const submitVenta = async () => {
    if (!form.tipo || !form.precio_venta) return;
    const cant = parseInt(form.cantidad) || 1;
    if (cant > form.tipo.stock_actual) {
      Alert.alert('Stock insuficiente', `Solo hay ${form.tipo.stock_actual} unidades disponibles.`);
      return;
    }
    setSubmitting(true);
    try {
      await tarjetasApi.vender(form.tipo.id, {
        cantidad: cant,
        precio_venta: parseFloat(form.precio_venta),
        medio_pago: form.medio_pago,
        cliente_nombre: form.cliente_nombre,
      });
      Alert.alert('✅ Venta registrada', `${cant} ${form.tipo.nombre} vendida(s) correctamente.`);
      setVentaModal(false);
      load();
    } catch (e: any) {
      Alert.alert('Error', e.message || 'No se pudo registrar la venta.');
    } finally {
      setSubmitting(false);
    }
  };

  const total = (parseInt(form.cantidad) || 0) * parseFloat(form.precio_venta || '0');

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#2E75B6" />
        <Text style={styles.loadingText}>Cargando tarjetas...</Text>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: '#F5F7FA' }}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>💳 Tarjetas de Recarga</Text>
      </View>

      <FlatList
        data={tipos}
        keyExtractor={item => item.id.toString()}
        numColumns={2}
        columnWrapperStyle={{ justifyContent: 'space-between', paddingHorizontal: 12 }}
        contentContainerStyle={{ padding: 4 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#2E75B6" />}
        renderItem={({ item }) => (
          <View style={{ width: '48%', marginBottom: 12 }}>
            <TipoCard tipo={item} onVender={() => openVenta(item)} />
          </View>
        )}
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text style={styles.emptyText}>No hay tipos de tarjeta configurados</Text>
          </View>
        }
      />

      {/* Modal Venta */}
      <Modal visible={ventaModal} animationType="slide" transparent>
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Vender — {form.tipo?.nombre}</Text>
            <Text style={styles.modalSub}>Stock: {form.tipo?.stock_actual} unidades</Text>

            <Text style={styles.inputLabel}>Cantidad</Text>
            <TextInput style={styles.input}
              value={form.cantidad} onChangeText={t => setForm(p => ({ ...p, cantidad: t }))}
              keyboardType="number-pad" />

            <Text style={styles.inputLabel}>Precio de venta (Bs.)</Text>
            <TextInput style={styles.input}
              value={form.precio_venta} onChangeText={t => setForm(p => ({ ...p, precio_venta: t }))}
              keyboardType="decimal-pad" />

            <Text style={styles.inputLabel}>Medio de pago</Text>
            <View style={styles.payRow}>
              {['CASH', 'QR', 'TRANSFER'].map(m => (
                <TouchableOpacity key={m} onPress={() => setForm(p => ({ ...p, medio_pago: m }))}
                  style={[styles.payBtn, form.medio_pago === m && styles.payBtnActive]}>
                  <Text style={[styles.payText, form.medio_pago === m && { color: '#FFF' }]}>{m}</Text>
                </TouchableOpacity>
              ))}
            </View>

            <Text style={styles.inputLabel}>Nombre cliente (opcional)</Text>
            <TextInput style={styles.input}
              value={form.cliente_nombre} onChangeText={t => setForm(p => ({ ...p, cliente_nombre: t }))}
              placeholder="Nombre del cliente" placeholderTextColor="#AAB4BE" />

            {total > 0 && (
              <View style={styles.totalBox}>
                <Text style={styles.totalLabel}>Total</Text>
                <Text style={styles.totalVal}>Bs. {total.toFixed(2)}</Text>
              </View>
            )}

            <View style={styles.modalActions}>
              <TouchableOpacity style={styles.cancelBtn} onPress={() => setVentaModal(false)}>
                <Text style={styles.cancelText}>Cancelar</Text>
              </TouchableOpacity>
              <TouchableOpacity style={styles.confirmBtn} onPress={submitVenta} disabled={submitting}>
                {submitting
                  ? <ActivityIndicator color="#FFF" />
                  : <Text style={styles.confirmText}>Confirmar</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#F5F7FA' },
  loadingText: { marginTop: 12, color: '#666', fontSize: 14 },
  header: { backgroundColor: '#1E3A5F', padding: 20, paddingTop: 52 },
  headerTitle: { color: '#FFF', fontSize: 20, fontWeight: '800' },
  card: {
    backgroundColor: '#FFF', borderRadius: 14, padding: 12,
    shadowColor: '#000', shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.07, shadowRadius: 8, elevation: 3,
  },
  cardHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  operadoraBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 20 },
  operadoraText: { color: '#FFF', fontWeight: '800', fontSize: 10 },
  stockNum: { fontSize: 16, fontWeight: '800' },
  tipoNombre: { fontSize: 13, fontWeight: '700', color: '#1E3A5F', marginBottom: 2 },
  tipoDenom: { fontSize: 11, color: '#888', marginBottom: 10 },
  cardRow: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 8 },
  metaLabel: { fontSize: 10, color: '#999' },
  metaVal: { fontSize: 12, fontWeight: '700', color: '#1E3A5F' },
  lowStockBanner: { backgroundColor: '#FDEDEC', borderRadius: 6, padding: 4, marginBottom: 8 },
  lowStockText: { fontSize: 10, color: '#C0392B', textAlign: 'center', fontWeight: '700' },
  venderBtn: { backgroundColor: '#1E3A5F', borderRadius: 10, paddingVertical: 10, alignItems: 'center' },
  venderBtnDisabled: { backgroundColor: '#CCC' },
  venderBtnText: { color: '#FFF', fontWeight: '800', fontSize: 13 },
  empty: { alignItems: 'center', paddingVertical: 40 },
  emptyText: { color: '#888', fontSize: 14 },
  // Modal
  modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.55)', justifyContent: 'flex-end' },
  modalCard: { backgroundColor: '#FFF', borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 24 },
  modalTitle: { fontSize: 18, fontWeight: '800', color: '#1E3A5F', marginBottom: 4 },
  modalSub: { fontSize: 12, color: '#888', marginBottom: 16 },
  inputLabel: { fontSize: 12, fontWeight: '700', color: '#555', marginBottom: 6, marginTop: 12 },
  input: { backgroundColor: '#F0F4F8', borderRadius: 10, paddingHorizontal: 14, paddingVertical: 12, fontSize: 15, color: '#1E3A5F' },
  payRow: { flexDirection: 'row', gap: 10, marginTop: 4 },
  payBtn: { flex: 1, paddingVertical: 10, borderRadius: 10, borderWidth: 2, borderColor: '#DDD', alignItems: 'center' },
  payBtnActive: { borderColor: '#2E75B6', backgroundColor: '#2E75B6' },
  payText: { fontWeight: '700', fontSize: 12, color: '#555' },
  totalBox: { backgroundColor: '#EBF3FB', borderRadius: 12, padding: 12, marginTop: 14, alignItems: 'center' },
  totalLabel: { fontSize: 12, color: '#2E75B6', fontWeight: '600' },
  totalVal: { fontSize: 22, fontWeight: '800', color: '#1E3A5F', marginTop: 2 },
  modalActions: { flexDirection: 'row', gap: 12, marginTop: 20 },
  cancelBtn: { flex: 1, borderWidth: 2, borderColor: '#DDD', borderRadius: 12, paddingVertical: 14, alignItems: 'center' },
  cancelText: { fontWeight: '700', color: '#555' },
  confirmBtn: { flex: 2, backgroundColor: '#1E3A5F', borderRadius: 12, paddingVertical: 14, alignItems: 'center' },
  confirmText: { color: '#FFF', fontWeight: '800', fontSize: 15 },
});
