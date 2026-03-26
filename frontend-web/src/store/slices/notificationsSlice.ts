import { createSlice, PayloadAction } from '@reduxjs/toolkit';

interface Notification {
  id:      string;
  message: string;
  type:    'success' | 'error' | 'warning' | 'info';
  read:    boolean;
}

interface NotificationsState {
  list: Notification[];
}

const initialState: NotificationsState = { list: [] };

const notificationsSlice = createSlice({
  name: 'notifications',
  initialState,
  reducers: {
    addNotification: (state, action: PayloadAction<Omit<Notification, 'id' | 'read'>>) => {
      state.list.unshift({
        ...action.payload,
        id:   Date.now().toString(),
        read: false,
      });
    },
    markAsRead: (state, action: PayloadAction<string>) => {
      const n = state.list.find(n => n.id === action.payload);
      if (n) n.read = true;
    },
    clearAll: (state) => { state.list = []; },
  },
});

export const { addNotification, markAsRead, clearAll } = notificationsSlice.actions;
export default notificationsSlice.reducer;