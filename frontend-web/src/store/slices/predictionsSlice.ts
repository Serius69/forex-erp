import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { api } from '../../services/api';

interface PredictionsState {
  data:    any;
  loading: boolean;
  error:   string | null;
}

const initialState: PredictionsState = { data: null, loading: false, error: null };

export const fetchPredictions = createAsyncThunk(
  'predictions/fetch',
  async (currencyPair: string = 'USD/BOB') => {
    const res = await api.get('/predictions/predictions/current/', {
      params: { currency_pair: currencyPair },
    });
    return res.data;
  }
);

const predictionsSlice = createSlice({
  name: 'predictions',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchPredictions.pending,   (state) => { state.loading = true; })
      .addCase(fetchPredictions.fulfilled, (state, action) => {
        state.loading = false;
        state.data    = action.payload;
      })
      .addCase(fetchPredictions.rejected,  (state, action) => {
        state.loading = false;
        state.error   = action.error.message || 'Error al cargar predicciones';
      });
  },
});

export default predictionsSlice.reducer;