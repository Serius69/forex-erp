import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { api } from '../../services/api';

interface TransactionsState {
  list:    any[];
  loading: boolean;
  error:   string | null;
  total:   number;
}

const initialState: TransactionsState = {
  list: [], loading: false, error: null, total: 0,
};

export const fetchTransactions = createAsyncThunk(
  'transactions/fetchAll',
  async (params?: object) => {
    const res = await api.get('/transactions/', { params });
    return res.data;
  }
);

const transactionsSlice = createSlice({
  name: 'transactions',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchTransactions.pending,   (state) => { state.loading = true; state.error = null; })
      .addCase(fetchTransactions.fulfilled, (state, action) => {
        state.loading = false;
        state.list    = action.payload.results ?? action.payload;
        state.total   = action.payload.count   ?? action.payload.length;
      })
      .addCase(fetchTransactions.rejected,  (state, action) => {
        state.loading = false;
        state.error   = action.error.message || 'Error al cargar transacciones';
      });
  },
});

export default transactionsSlice.reducer;