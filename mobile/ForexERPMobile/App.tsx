import React, { useEffect } from 'react';
import { StatusBar, LogBox } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { Provider } from 'react-redux';
import { QueryClient, QueryClientProvider } from 'react-query';
import { PaperProvider } from 'react-native-paper';
import SplashScreen from 'react-native-splash-screen';
import Toast from 'react-native-toast-message';
import { GestureHandlerRootView } from 'react-native-gesture-handler';

import { store } from './src/store';
import { theme } from './src/constants/theme';
import { AuthProvider } from './src/contexts/AuthContext';
import { NotificationProvider } from './src/contexts/NotificationContext';
import RootNavigator from './src/navigation/RootNavigator';
import { toastConfig } from './src/components/common/ToastConfig';
import NetworkStatus from './src/components/common/NetworkStatus';

// Ignorar warnings específicos en desarrollo
LogBox.ignoreLogs([
  'Non-serializable values were found in the navigation state',
]);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

function App(): JSX.Element {
  useEffect(() => {
    // Ocultar splash screen después de cargar
    setTimeout(() => {
      SplashScreen.hide();
    }, 1000);
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <Provider store={store}>
        <QueryClientProvider client={queryClient}>
          <PaperProvider theme={theme}>
            <NavigationContainer>
              <AuthProvider>
                <NotificationProvider>
                  <StatusBar
                    barStyle="light-content"
                    backgroundColor={theme.colors.primary}
                  />
                  <NetworkStatus />
                  <RootNavigator />
                  <Toast config={toastConfig} />
                </NotificationProvider>
              </AuthProvider>
            </NavigationContainer>
          </PaperProvider>
        </QueryClientProvider>
      </Provider>
    </GestureHandlerRootView>
  );
}

export default App;