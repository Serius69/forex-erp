import { configureStore } from '@reduxjs/toolkit';
import dashboardReducer from './slices/dashboardSlice';
import transactionsReducer from './slices/transactionsSlice';
import inventoryReducer from './slices/inventorySlice';
import predictionsReducer from './slices/predictionsSlice';
import notificationsReducer from './slices/notificationsSlice';

export const store = configureStore({
  reducer: {
    dashboard: dashboardReducer,
    transactions: transactionsReducer,
    inventory: inventoryReducer,
    predictions: predictionsReducer,
    notifications: notificationsReducer,
  },
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;