/* eslint-env jest */
// jest.setup.js — mocks de módulos nativos para el entorno de pruebas.

// AsyncStorage no tiene implementación nativa en Jest: usar el mock oficial.
jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

// NetInfo no tiene implementación nativa en Jest: usar el mock oficial.
jest.mock('@react-native-community/netinfo', () =>
  require('@react-native-community/netinfo/jest/netinfo-mock'),
);

// Mock del contexto de safe-area (sin medición nativa en Jest).
jest.mock(
  'react-native-safe-area-context',
  () => require('react-native-safe-area-context/jest/mock').default,
);

// El barrel de react-native expone BackHandler/Linking sin sus métodos en Jest;
// React Navigation los usa al montar NavigationContainer, así que los stubbeamos.
const ReactNative = require('react-native');

Object.defineProperty(ReactNative, 'BackHandler', {
  configurable: true,
  value: {
    addEventListener: jest.fn(() => ({remove: jest.fn()})),
    removeEventListener: jest.fn(),
    exitApp: jest.fn(),
  },
});

Object.defineProperty(ReactNative, 'Linking', {
  configurable: true,
  value: {
    addEventListener: jest.fn(() => ({remove: jest.fn()})),
    removeEventListener: jest.fn(),
    getInitialURL: jest.fn(() => Promise.resolve(null)),
    canOpenURL: jest.fn(() => Promise.resolve(true)),
    openURL: jest.fn(() => Promise.resolve()),
  },
});
