import React, { useState } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  KeyboardAvoidingView, Platform, ScrollView, ActivityIndicator, Alert,
} from 'react-native';
import { useAuth } from '../hooks/useAuth';

export default function LoginScreen() {
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [pin, setPin] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const handleLogin = async () => {
    if (!username.trim() || !password.trim() || !pin.trim()) {
      Alert.alert('Campos requeridos', 'Por favor completa usuario, contraseña y PIN.');
      return;
    }
    if (pin.length !== 6) {
      Alert.alert('PIN inválido', 'El PIN debe tener exactamente 6 dígitos.');
      return;
    }

    setLoading(true);
    try {
      await login({ username: username.trim(), password, pin });
    } catch (err: any) {
      Alert.alert(
        'Error de acceso',
        err.message === 'UNAUTHORIZED'
          ? 'Usuario, contraseña o PIN incorrectos.'
          : 'No se pudo conectar al servidor. Verifica tu conexión.',
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.logo}>💱</Text>
          <Text style={styles.title}>Forex ERP</Text>
          <Text style={styles.subtitle}>Casa de Cambio de Divisas</Text>
        </View>

        {/* Card de login */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Iniciar Sesión</Text>

          <View style={styles.field}>
            <Text style={styles.label}>Usuario</Text>
            <TextInput
              style={styles.input}
              placeholder="Ingresa tu usuario"
              placeholderTextColor="#AAB4BE"
              value={username}
              onChangeText={setUsername}
              autoCapitalize="none"
              autoCorrect={false}
            />
          </View>

          <View style={styles.field}>
            <Text style={styles.label}>Contraseña</Text>
            <View style={styles.passwordRow}>
              <TextInput
                style={[styles.input, styles.passwordInput]}
                placeholder="Ingresa tu contraseña"
                placeholderTextColor="#AAB4BE"
                value={password}
                onChangeText={setPassword}
                secureTextEntry={!showPassword}
              />
              <TouchableOpacity
                style={styles.eyeBtn}
                onPress={() => setShowPassword(v => !v)}
              >
                <Text style={styles.eyeIcon}>{showPassword ? '🙈' : '👁️'}</Text>
              </TouchableOpacity>
            </View>
          </View>

          <View style={styles.field}>
            <Text style={styles.label}>PIN de Operación (6 dígitos)</Text>
            <TextInput
              style={styles.input}
              placeholder="••••••"
              placeholderTextColor="#AAB4BE"
              value={pin}
              onChangeText={t => setPin(t.replace(/\D/g, '').slice(0, 6))}
              keyboardType="numeric"
              secureTextEntry
              maxLength={6}
            />
          </View>

          <TouchableOpacity
            style={[styles.btn, loading && styles.btnDisabled]}
            onPress={handleLogin}
            disabled={loading}
            activeOpacity={0.8}
          >
            {loading ? (
              <ActivityIndicator color="#FFF" />
            ) : (
              <Text style={styles.btnText}>Ingresar al Sistema</Text>
            )}
          </TouchableOpacity>
        </View>

        <Text style={styles.version}>Forex ERP v1.0 — Bolivia 2025</Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#1E3A5F' },
  scroll: { flexGrow: 1, justifyContent: 'center', padding: 24 },
  header: { alignItems: 'center', marginBottom: 32 },
  logo: { fontSize: 56, marginBottom: 8 },
  title: { fontSize: 32, fontWeight: '800', color: '#FFFFFF', letterSpacing: 1 },
  subtitle: { fontSize: 14, color: '#7FAFD4', marginTop: 4 },
  card: {
    backgroundColor: '#FFFFFF',
    borderRadius: 20,
    padding: 28,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.2,
    shadowRadius: 16,
    elevation: 10,
  },
  cardTitle: { fontSize: 20, fontWeight: '700', color: '#1E3A5F', marginBottom: 24 },
  field: { marginBottom: 18 },
  label: { fontSize: 13, fontWeight: '600', color: '#555', marginBottom: 6 },
  input: {
    backgroundColor: '#F5F7FA',
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    color: '#1E3A5F',
    borderWidth: 1,
    borderColor: '#E0E8F0',
  },
  passwordRow: { flexDirection: 'row', alignItems: 'center' },
  passwordInput: { flex: 1 },
  eyeBtn: { position: 'absolute', right: 12 },
  eyeIcon: { fontSize: 18 },
  btn: {
    backgroundColor: '#2E75B6',
    borderRadius: 12,
    paddingVertical: 15,
    alignItems: 'center',
    marginTop: 8,
  },
  btnDisabled: { opacity: 0.6 },
  btnText: { color: '#FFF', fontSize: 16, fontWeight: '700', letterSpacing: 0.5 },
  version: { textAlign: 'center', color: '#5A7A9A', fontSize: 12, marginTop: 24 },
});
