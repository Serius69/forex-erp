import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';

/**
 * Banner rojo de error con reintento. Se toca en cualquier parte para
 * volver a intentar la operación fallida.
 */
export default function ErrorBanner({
  message,
  onRetry,
}: {
  message:  string;
  onRetry?: () => void;
}) {
  return (
    <TouchableOpacity
      style={styles.banner}
      onPress={onRetry}
      disabled={!onRetry}
      activeOpacity={0.8}
      accessibilityRole="button"
      accessibilityLabel={`Error: ${message}. Toca para reintentar`}
    >
      <Text style={styles.icon}>⚠️</Text>
      <View style={styles.content}>
        <Text style={styles.message}>{message}</Text>
        {onRetry ? <Text style={styles.retry}>Toca para reintentar</Text> : null}
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  banner:  { flexDirection: 'row', alignItems: 'center', backgroundColor: '#FDEDEC', borderColor: '#E74C3C', borderWidth: 1, borderRadius: 12, padding: 14, margin: 16 },
  icon:    { fontSize: 22, marginRight: 12 },
  content: { flex: 1 },
  message: { color: '#C0392B', fontSize: 13, fontWeight: '700' },
  retry:   { color: '#E74C3C', fontSize: 12, fontWeight: '600', marginTop: 4 },
});
