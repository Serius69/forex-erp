import React from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';

/** Indicador de carga centrado con texto opcional. */
export default function LoadingView({ text }: { text?: string }) {
  return (
    <View style={styles.center}>
      <ActivityIndicator size="large" color="#2E75B6" />
      {text ? <Text style={styles.text}>{text}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', paddingVertical: 60, backgroundColor: '#F5F7FA' },
  text:   { marginTop: 12, color: '#888', fontSize: 14, fontWeight: '600' },
});
