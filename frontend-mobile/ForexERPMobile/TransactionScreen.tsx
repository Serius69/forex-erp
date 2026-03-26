import React, { useState, useCallback } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ScrollView, Alert, ActivityIndicator, Modal, KeyboardAvoidingView, Platform,
} from 'react-native';
import { transactionsApi, ratesApi } from '../services/api';
import { useAuth } from '../hooks/useAuth';
import { TransactionType, PaymentMethod, Customer, NewTransactionPayload } from '../types';

const CURRENCIES = ['USD', 'EUR', 'BRL', 'ARS'];
const PAYMENT_METHODS: { value: PaymentMethod; label: string; icon: string }[] = [
  { value: 'CASH', label: 'Efectivo', icon: '💵' },
  { value: 'TRANSFER', label: 'Transferencia', icon: '🏦' },
  { value: 'QR', label: 'QR', icon: '📱' },
];

function ToggleButton({
  selected, label, onPress, color,
}: { selected: boolean; label: string; onPress: () => void; color: string }) {
  return (
    <TouchableOpacity
      style={[styles.toggleBtn, selected && { backgroundColor: color, borderColor: color }]}
      onPress={onPress}
      activeOpacity={0.8}
    >
      <Text style={[styles.toggleText, selected && { color: '#FFF' }]}>{label}</Text>
    </TouchableOpacity>
  );
}

export default function TransactionScreen() {
  const { pin } = useAuth();
  const [txType, setTxType] = useState<TransactionType>('SELL');
  const [currency, setCurrency] = useState('USD');
  const [amount, setAmount] = useState('');
  const [rate, setRate] = useState('');
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>('CASH');
  const [docNumber, setDocNumber] = useState('');
  const [customerName, setCustomerName] = useState('');
  const [foundCustomer, setFoundCustomer] = useState<Customer | null>(null);
  const [notes, setNotes] = useState('');
  const [loading, setLoading] = useState(false);
  const [searchingCustomer, setSearchingCustomer] = useState(false);
  const [successModal, setSuccessModal] = useState(false);
  const [lastTxNumber, setLastTxNumber] = useState('');

  const amountNum = parseFloat(amount) || 0;
  const rateNum = parseFloat(rate) || 0;
  const totalBOB = amountNum * rateNum;

  const searchCustomer = useCallback(async (doc: string) => {
    setDocNumber(doc);
    if (doc.length < 5) {
      setFoundCustomer(null);
      setCustomerName('');
      return;
    }
    setSearchingCustomer(true);
    try {
      const customer = await transactionsApi.searchCustomer(doc);
      if (customer) {
        setFoundCustomer(customer);
        setCustomerName(customer.full_name);
      } else {
        setFoundCustomer(null);
        setCustomerName('');
      }
    } finally {
      setSearchingCustomer(false);
    }
  }, []);

  const loadCurrentRate = async () => {
    try {
      const rates = await ratesApi.getCurrent();
      if (rates[currency]) {
        const r = txType === 'BUY' ? rates[currency].buy : rates[currency].sell;
        setRate(r.toFixed(4));
      }
    } catch {
      Alert.alert('Error', 'No se pudo obtener la tasa actual.');
    }
  };

  const handleSubmit = async () => {
    if (!docNumber || !customerName || !amount || !rate) {
      Alert.alert('Campos requeridos', 'Por favor completa todos los campos obligatorios.');
      return;
    }
    if (amountNum <= 0 || rateNum <= 0) {
      Alert.alert('Valores inválidos', 'El monto y la tasa deben ser mayores a cero.');
      return;
    }
    if (!pin) {
      Alert.alert('PIN requerido', 'No se encontró tu PIN de operación. Por favor vuelve a iniciar sesión.');
      return;
    }

    setLoading(true);
    try {
      const payload: NewTransactionPayload = {
        transaction_type: txType,
        document_number: docNumber,
        customer_name: customerName,
        customer_id: foundCustomer?.id,
        currency_from: currency,
        amount_from: amountNum,
        exchange_rate: rateNum,
        payment_method: paymentMethod,
        notes: notes.trim(),
      };

      const res = await transactionsApi.create(payload, pin);
      setLastTxNumber(res.transaction.transaction_number);
      setSuccessModal(true);
      resetForm();
    } catch (err: any) {
      Alert.alert('Error al registrar', err.message ?? 'Ocurrió un error inesperado.');
    } finally {
      setLoading(false);
    }
  };

  const resetForm = () => {
    setAmount(''); setRate(''); setDocNumber('');
    setCustomerName(''); setFoundCustomer(null); setNotes('');
  };

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView style={styles.container} keyboardShouldPersistTaps="handled">
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.headerTitle}>💱 Nueva Transacción</Text>
        </View>

        <View style={styles.body}>
          {/* Tipo de transacción */}
          <Text style={styles.label}>Tipo de Operación</Text>
          <View style={styles.toggleRow}>
            <ToggleButton
              selected={txType === 'SELL'}
              label="Venta de Divisas"
              onPress={() => setTxType('SELL')}
              color="#C0392B"
            />
            <ToggleButton
              selected={txType === 'BUY'}
              label="Compra de Divisas"
              onPress={() => setTxType('BUY')}
              color="#1F7A4D"
            />
          </View>

          {/* Divisa */}
          <Text style={styles.label}>Divisa</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.currencyScroll}>
            {CURRENCIES.map(c => (
              <TouchableOpacity
                key={c}
                style={[styles.currencyBtn, currency === c && styles.currencyBtnActive]}
                onPress={() => setCurrency(c)}
              >
                <Text style={[styles.currencyText, currency === c && styles.currencyTextActive]}>{c}</Text>
              </TouchableOpacity>
            ))}
          </ScrollView>

          {/* Documento del cliente */}
          <Text style={styles.label}>Documento del Cliente *</Text>
          <View style={styles.inputRow}>
            <TextInput
              style={[styles.input, { flex: 1 }]}
              placeholder="Nro. de documento"
              placeholderTextColor="#AAB4BE"
              value={docNumber}
              onChangeText={searchCustomer}
              keyboardType="numeric"
            />
            {searchingCustomer && <ActivityIndicator color="#2E75B6" style={{ marginLeft: 8 }} />}
            {foundCustomer && <Text style={styles.checkIcon}>✅</Text>}
          </View>
          {foundCustomer && (
            <View style={styles.customerFound}>
              <Text style={styles.customerFoundText}>
                👤 {foundCustomer.full_name}
                {foundCustomer.is_frequent ? '  ⭐ Frecuente' : ''}
              </Text>
            </View>
          )}

          <Text style={styles.label}>Nombre del Cliente *</Text>
          <TextInput
            style={[styles.input, !!foundCustomer && styles.inputDisabled]}
            placeholder="Nombre completo"
            placeholderTextColor="#AAB4BE"
            value={customerName}
            onChangeText={setCustomerName}
            editable={!foundCustomer}
          />

          {/* Monto */}
          <Text style={styles.label}>Monto en {currency} *</Text>
          <TextInput
            style={styles.input}
            placeholder={`Ej: 500.00 ${currency}`}
            placeholderTextColor="#AAB4BE"
            value={amount}
            onChangeText={setAmount}
            keyboardType="decimal-pad"
          />

          {/* Tasa */}
          <Text style={styles.label}>Tasa de Cambio *</Text>
          <View style={styles.inputRow}>
            <TextInput
              style={[styles.input, { flex: 1 }]}
              placeholder="Ej: 6.9200"
              placeholderTextColor="#AAB4BE"
              value={rate}
              onChangeText={setRate}
              keyboardType="decimal-pad"
            />
            <TouchableOpacity style={styles.rateBtn} onPress={loadCurrentRate}>
              <Text style={styles.rateBtnText}>Actual</Text>
            </TouchableOpacity>
          </View>

          {/* Total calculado */}
          {totalBOB > 0 && (
            <View style={styles.totalBox}>
              <Text style={styles.totalLabel}>Total en Bolivianos</Text>
              <Text style={styles.totalValue}>
                Bs. {totalBOB.toLocaleString('es-BO', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </Text>
            </View>
          )}

          {/* Método de pago */}
          <Text style={styles.label}>Método de Pago</Text>
          <View style={styles.paymentRow}>
            {PAYMENT_METHODS.map(m => (
              <TouchableOpacity
                key={m.value}
                style={[styles.paymentBtn, paymentMethod === m.value && styles.paymentBtnActive]}
                onPress={() => setPaymentMethod(m.value)}
              >
                <Text style={styles.paymentIcon}>{m.icon}</Text>
                <Text style={[styles.paymentLabel, paymentMethod === m.value && styles.paymentLabelActive]}>
                  {m.label}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* Notas */}
          <Text style={styles.label}>Notas (Opcional)</Text>
          <TextInput
            style={[styles.input, styles.textarea]}
            placeholder="Observaciones..."
            placeholderTextColor="#AAB4BE"
            value={notes}
            onChangeText={setNotes}
            multiline
            numberOfLines={3}
          />

          {/* Botones */}
          <TouchableOpacity
            style={[styles.submitBtn, loading && styles.btnDisabled]}
            onPress={handleSubmit}
            disabled={loading}
            activeOpacity={0.85}
          >
            {loading
              ? <ActivityIndicator color="#FFF" />
              : <Text style={styles.submitText}>✅ Registrar Transacción</Text>
            }
          </TouchableOpacity>

          <TouchableOpacity style={styles.clearBtn} onPress={resetForm}>
            <Text style={styles.clearText}>Limpiar formulario</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>

      {/* Modal de éxito */}
      <Modal transparent visible={successModal} animationType="fade">
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalIcon}>🎉</Text>
            <Text style={styles.modalTitle}>Transacción Registrada</Text>
            <Text style={styles.modalSub}>Comprobante N°</Text>
            <Text style={styles.modalTxNum}>{lastTxNumber}</Text>
            <TouchableOpacity style={styles.modalBtn} onPress={() => setSuccessModal(false)}>
              <Text style={styles.modalBtnText}>Aceptar</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F5F7FA' },
  header: { backgroundColor: '#1E3A5F', padding: 20, paddingTop: 52 },
  headerTitle: { color: '#FFF', fontSize: 20, fontWeight: '800' },
  body: { padding: 16 },
  label: { fontSize: 13, fontWeight: '700', color: '#444', marginBottom: 6, marginTop: 16 },
  input: { backgroundColor: '#FFF', borderRadius: 10, paddingHorizontal: 14, paddingVertical: 12, fontSize: 15, color: '#1E3A5F', borderWidth: 1, borderColor: '#E0E8F0' },
  inputDisabled: { backgroundColor: '#F0F4F8', color: '#888' },
  inputRow: { flexDirection: 'row', alignItems: 'center' },
  textarea: { height: 80, textAlignVertical: 'top' },
  toggleRow: { flexDirection: 'row', gap: 10 },
  toggleBtn: { flex: 1, paddingVertical: 12, borderRadius: 10, borderWidth: 2, borderColor: '#DDD', alignItems: 'center' },
  toggleText: { fontWeight: '700', fontSize: 13, color: '#555' },
  currencyScroll: { marginBottom: 4 },
  currencyBtn: { paddingHorizontal: 20, paddingVertical: 10, borderRadius: 20, borderWidth: 2, borderColor: '#DDD', marginRight: 8, backgroundColor: '#FFF' },
  currencyBtnActive: { borderColor: '#2E75B6', backgroundColor: '#2E75B6' },
  currencyText: { fontWeight: '700', fontSize: 14, color: '#555' },
  currencyTextActive: { color: '#FFF' },
  checkIcon: { marginLeft: 8, fontSize: 20 },
  customerFound: { backgroundColor: '#EBF7EE', borderRadius: 8, padding: 10, marginTop: 6 },
  customerFoundText: { color: '#1F7A4D', fontWeight: '600', fontSize: 13 },
  rateBtn: { backgroundColor: '#2E75B6', paddingHorizontal: 14, paddingVertical: 12, borderRadius: 10, marginLeft: 8 },
  rateBtnText: { color: '#FFF', fontWeight: '700', fontSize: 13 },
  totalBox: { backgroundColor: '#EBF3FB', borderRadius: 12, padding: 14, marginTop: 12, alignItems: 'center' },
  totalLabel: { fontSize: 12, color: '#2E75B6', fontWeight: '600' },
  totalValue: { fontSize: 24, fontWeight: '800', color: '#1E3A5F', marginTop: 4 },
  paymentRow: { flexDirection: 'row', gap: 10 },
  paymentBtn: { flex: 1, alignItems: 'center', paddingVertical: 14, borderRadius: 12, borderWidth: 2, borderColor: '#E0E8F0', backgroundColor: '#FFF' },
  paymentBtnActive: { borderColor: '#2E75B6', backgroundColor: '#EBF3FB' },
  paymentIcon: { fontSize: 22 },
  paymentLabel: { fontSize: 11, fontWeight: '700', color: '#888', marginTop: 4 },
  paymentLabelActive: { color: '#2E75B6' },
  submitBtn: { backgroundColor: '#1E3A5F', borderRadius: 14, paddingVertical: 16, alignItems: 'center', marginTop: 24 },
  btnDisabled: { opacity: 0.6 },
  submitText: { color: '#FFF', fontSize: 16, fontWeight: '800' },
  clearBtn: { alignItems: 'center', paddingVertical: 14, marginTop: 8 },
  clearText: { color: '#999', fontSize: 14, fontWeight: '600' },
  modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'center', alignItems: 'center' },
  modalCard: { backgroundColor: '#FFF', borderRadius: 20, padding: 32, alignItems: 'center', width: '80%' },
  modalIcon: { fontSize: 52, marginBottom: 12 },
  modalTitle: { fontSize: 20, fontWeight: '800', color: '#1E3A5F', marginBottom: 8 },
  modalSub: { fontSize: 13, color: '#888' },
  modalTxNum: { fontSize: 22, fontWeight: '800', color: '#2E75B6', marginTop: 4, marginBottom: 20 },
  modalBtn: { backgroundColor: '#2E75B6', paddingHorizontal: 40, paddingVertical: 14, borderRadius: 12 },
  modalBtnText: { color: '#FFF', fontWeight: '800', fontSize: 15 },
});
