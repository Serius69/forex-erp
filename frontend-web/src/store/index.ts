// src/store/index.ts
// Configuración del store Redux Toolkit.
import { configureStore } from '@reduxjs/toolkit';
import ratesReducer from './ratesSlice';

export const store = configureStore({
  reducer: {
    rates: ratesReducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      serializableCheck: {
        // Ignorar rutas con objetos no serializables (e.g. Date en predicted values)
        ignoredPaths: ['rates.digital.lastFetch', 'rates.lastWsUpdate'],
      },
    }),
});

export type RootState   = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
