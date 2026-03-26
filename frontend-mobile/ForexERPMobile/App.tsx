import React from 'react';
import { StatusBar } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { AuthProvider } from './src/hooks/useAuth';
import AppNavigator from './src/navigation/AppNavigator';

/**
 * Forex ERP — App Móvil
 * React Native + TypeScript
 *
 * Estructura:
 *   App.tsx                          ← Este archivo (punto de entrada)
 *   src/
 *     types/index.ts                 ← Tipos TypeScript globales
 *     services/api.ts                ← Cliente HTTP para el backend Django
 *     hooks/useAuth.tsx              ← Contexto y hook de autenticación
 *     navigation/AppNavigator.tsx    ← Stack + Bottom Tabs
 *     screens/
 *       LoginScreen.tsx              ← Pantalla de login con JWT + PIN
 *       DashboardScreen.tsx          ← Tasas en tiempo real + predicciones + resumen
 *       TransactionScreen.tsx        ← Formulario de nueva transacción
 *       InventoryScreen.tsx          ← Control de stock por divisa/sucursal
 *       AlertsScreen.tsx             ← Alertas activas con filtro por severidad
 *       ReportsScreen.tsx            ← Reportes diarios por divisa con selector de fecha
 */
export default function App() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <NavigationContainer>
          <StatusBar barStyle="light-content" backgroundColor="#1E3A5F" />
          <AppNavigator />
        </NavigationContainer>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
