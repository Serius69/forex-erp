import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { api } from '../../services/api';

interface InventoryState {
  list:    any[];
  loading: boolean;
  error:   string | null;
}

const initialState: InventoryState = { list: [], loading: false, error: null };

export const fetchInventory = createAsyncThunk(
  'inventory/fetchAll',
  async () => {
    const res = await api.get('/inventory/');
    return res.data;
  }
);

const inventorySlice = createSlice({
  name: 'inventory',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchInventory.pending,   (state) => { state.loading = true; })
      .addCase(fetchInventory.fulfilled, (state, action) => {
        state.loading = false;
        state.list    = action.payload.results ?? action.payload;
      })
      .addCase(fetchInventory.rejected,  (state, action) => {
        state.loading = false;
        state.error   = action.error.message || 'Error al cargar inventario';
      });
  },
});

export default inventorySlice.reducer;