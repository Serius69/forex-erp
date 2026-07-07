// src/navigation/AppNavigator.tsx
import React from 'react';
import { createNativeStackNavigator }  from '@react-navigation/native-stack';
import { createBottomTabNavigator }    from '@react-navigation/bottom-tabs';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { useAuth }           from '../hooks/useAuth';
import { RootStackParamList, BottomTabParamList } from '../types/index';
import LoginScreen           from '../screens/LoginScreen';
import DashboardScreen       from '../screens/DashboardScreen';
import TransactionScreen     from '../screens/TransactionScreen';
import InventoryScreen       from '../screens/InventoryScreen';
import TarjetasScreen        from '../screens/TarjetasScreen';
import ReportsScreen         from '../screens/ReportsScreen';
import AlertsScreen          from '../screens/AlertsScreen';

const Stack = createNativeStackNavigator<RootStackParamList>();
const Tab   = createBottomTabNavigator<BottomTabParamList>();

function TabIcon({ icon, color }: { icon: string; color: string }) {
  return <Text style={{ fontSize: 20, color }}>{icon}</Text>;
}

function MainTabs() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerShown:          false,
        tabBarStyle:          styles.tabBar,
        tabBarActiveTintColor:   '#2E75B6',
        tabBarInactiveTintColor: '#999',
        tabBarLabelStyle:     styles.tabLabel,
      }}
    >
      <Tab.Screen name="Dashboard"   component={DashboardScreen}
        options={{ title: 'Inicio',       tabBarIcon: ({ color }) => <TabIcon icon="📊" color={color} /> }} />
      <Tab.Screen name="Transaction" component={TransactionScreen}
        options={{ title: 'Transacción',  tabBarIcon: ({ color }) => <TabIcon icon="💱" color={color} /> }} />
      <Tab.Screen name="Inventory"   component={InventoryScreen}
        options={{ title: 'Inventario',   tabBarIcon: ({ color }) => <TabIcon icon="🏦" color={color} /> }} />
      <Tab.Screen name="Tarjetas"    component={TarjetasScreen}
        options={{ title: 'Tarjetas',     tabBarIcon: ({ color }) => <TabIcon icon="💳" color={color} /> }} />
      <Tab.Screen name="Reports"     component={ReportsScreen}
        options={{ title: 'Reportes',     tabBarIcon: ({ color }) => <TabIcon icon="📈" color={color} /> }} />
      <Tab.Screen name="Alerts"      component={AlertsScreen}
        options={{ title: 'Alertas',      tabBarIcon: ({ color }) => <TabIcon icon="🔔" color={color} /> }} />
    </Tab.Navigator>
  );
}

export default function AppNavigator() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <View style={styles.loader}>
        <ActivityIndicator size="large" color="#2E75B6" />
      </View>
    );
  }

  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      {isAuthenticated
        ? <Stack.Screen name="Main"  component={MainTabs} />
        : <Stack.Screen name="Login" component={LoginScreen} />}
    </Stack.Navigator>
  );
}

const styles = StyleSheet.create({
  loader:   { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#F5F7FA' },
  tabBar:   { backgroundColor: '#FFFFFF', borderTopColor: '#E8ECF0', borderTopWidth: 1, height: 60, paddingBottom: 8, paddingTop: 6 },
  tabLabel: { fontSize: 10, fontWeight: '600' },
});