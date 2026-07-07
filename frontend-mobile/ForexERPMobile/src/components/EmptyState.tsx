import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

/** Estado vacío: icono emoji grande + texto descriptivo. */
export default function EmptyState({
  icon = '📭',
  text,
}: {
  icon?: string;
  text:  string;
}) {
  return (
    <View style={styles.empty}>
      <Text style={styles.icon}>{icon}</Text>
      <Text style={styles.text}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  empty: { alignItems: 'center', paddingVertical: 40 },
  icon:  { fontSize: 52, marginBottom: 12 },
  text:  { color: '#AAB4BE', fontSize: 15, fontWeight: '600', textAlign: 'center' },
});
