module.exports = {
  preset: 'react-native',
  setupFiles: ['./jest.setup.js'],
  transformIgnorePatterns: [
    'node_modules/(?!(@react-native|react-native|@react-navigation|react-native-chart-kit|react-native-svg|react-native-vector-icons|react-native-screens|react-native-safe-area-context)/)',
  ],
};
