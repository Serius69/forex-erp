import { createSlice, createAsyncThunk, PayloadAction } from '@reduxjs/toolkit';
import { api } from '../../services/api';

interface DashboardState {
  stats: {
    todayTransactions: number;
    todayVolume: number;
    todayProfit: number;
    activeCustomers: number;
  } | null;
  rates: Record<string, any>;
  loading: boolean;
  error: string | null;
}

const initialState: DashboardState = {
  stats: null,
  rates: {},
  loading: false,
  error: null,
};

export const fetchDashboardStats = createAsyncThunk(
  'dashboard/fetchStats',
  async () => {
    const response = await api.get('/dashboard/stats/');
    return response.data;
  }
);

export const fetchRates = createAsyncThunk(
  'dashboard/fetchRates',
  async () => {
    const response = await api.get('/rates/current/');
    return response.data;
  }
);

const dashboardSlice = createSlice({
  name: 'dashboard',
  initialState,
  reducers: {
    updateRates: (state, action: PayloadAction<Record<string, any>>) => {
      state.rates = action.payload;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchDashboardStats.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchDashboardStats.fulfilled, (state, action) => {
        state.loading = false;
        state.stats = action.payload;
      })
      .addCase(fetchDashboardStats.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message || 'Error al cargar estadísticas';
      })
      .addCase(fetchRates.fulfilled, (state, action) => {
        state.rates = action.payload;
      });
  },
});

export const { updateRates } = dashboardSlice.actions;
export default dashboardSlice.reducer;