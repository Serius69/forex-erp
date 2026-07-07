// src/store/ratesSlice.ts
// Redux Toolkit slice para el estado global de tasas de cambio.
import { createSlice, createAsyncThunk, PayloadAction } from '@reduxjs/toolkit';
import { ratesApi, LiveRate, ExchangeRate, ForecastResult, ModelHealthReport } from '../services/ratesApi';

// ── Estado ────────────────────────────────────────────────────────────────────

interface DigitalRatesState {
  byCode:   Record<string, LiveRate>;
  loading:  boolean;
  error:    string | null;
  lastFetch: string | null;
}

interface PredictionsState {
  byPair:    Record<string, ForecastResult>;
  health:    ModelHealthReport | null;
  loading:   boolean;
  error:     string | null;
}

interface ManualRatesState {
  rates:    ExchangeRate[];
  loading:  boolean;
  error:    string | null;
}

interface RatesState {
  digital:    DigitalRatesState;
  predictions: PredictionsState;
  manual:     ManualRatesState;
  wsConnected: boolean;
  lastWsUpdate: string | null;
}

const initialState: RatesState = {
  digital: {
    byCode:    {},
    loading:   false,
    error:     null,
    lastFetch: null,
  },
  predictions: {
    byPair:  {},
    health:  null,
    loading: false,
    error:   null,
  },
  manual: {
    rates:   [],
    loading: false,
    error:   null,
  },
  wsConnected:  false,
  lastWsUpdate: null,
};

// ── Thunks ────────────────────────────────────────────────────────────────────

export const fetchLiveRate = createAsyncThunk(
  'rates/fetchLiveRate',
  async (currency: string, { rejectWithValue }) => {
    try {
      const data = await ratesApi.getLiveRate(currency);
      return { currency, data };
    } catch (e: any) {
      return rejectWithValue(e?.response?.data?.error ?? 'Error al obtener tasa en vivo');
    }
  }
);

export const fetchAllLiveRates = createAsyncThunk(
  'rates/fetchAllLiveRates',
  async (currencies: string[] = ['USD', 'EUR', 'BRL', 'PEN', 'CLP', 'ARS'], { rejectWithValue }) => {
    try {
      const results = await Promise.allSettled(
        currencies.map(c => ratesApi.getLiveRate(c).then(d => ({ currency: c, data: d })))
      );
      const fulfilled: { currency: string; data: LiveRate }[] = [];
      results.forEach(r => { if (r.status === 'fulfilled') fulfilled.push(r.value); });
      return fulfilled;
    } catch (e: any) {
      return rejectWithValue('Error al obtener tasas en vivo');
    }
  }
);

export const fetchForecast = createAsyncThunk(
  'rates/fetchForecast',
  async ({ pair, horizon = '24h' }: { pair: string; horizon?: '1h' | '4h' | '24h' | '7d' }, { rejectWithValue }) => {
    try {
      const data = await ratesApi.getForecast(pair, horizon);
      return { pair, data };
    } catch (e: any) {
      return rejectWithValue(e?.response?.data?.error ?? `Error al obtener pronóstico para ${pair}`);
    }
  }
);

export const fetchPredictionHealth = createAsyncThunk(
  'rates/fetchPredictionHealth',
  async (_, { rejectWithValue }) => {
    try {
      return await ratesApi.getPredictionHealth();
    } catch (e: any) {
      return rejectWithValue('Error al obtener estado de modelos ML');
    }
  }
);

export const fetchManualRates = createAsyncThunk(
  'rates/fetchManualRates',
  async (_, { rejectWithValue }) => {
    try {
      const all = await ratesApi.getExchangeRates();
      return all.filter((r: ExchangeRate) => r.source_method === 'MANUAL');
    } catch (e: any) {
      return rejectWithValue('Error al obtener tasas manuales');
    }
  }
);

export const createManualRate = createAsyncThunk(
  'rates/createManualRate',
  async (data: Partial<ExchangeRate>, { dispatch, rejectWithValue }) => {
    try {
      const result = await ratesApi.createRate(data);
      dispatch(fetchManualRates());
      return result;
    } catch (e: any) {
      return rejectWithValue(e?.response?.data ?? 'Error al crear tasa');
    }
  }
);

export const updateManualRate = createAsyncThunk(
  'rates/updateManualRate',
  async ({ id, data }: { id: number; data: Partial<ExchangeRate> }, { dispatch, rejectWithValue }) => {
    try {
      const result = await ratesApi.updateRate(id, data);
      dispatch(fetchManualRates());
      return result;
    } catch (e: any) {
      return rejectWithValue(e?.response?.data ?? 'Error al actualizar tasa');
    }
  }
);

// ── Slice ─────────────────────────────────────────────────────────────────────

const ratesSlice = createSlice({
  name: 'rates',
  initialState,
  reducers: {
    setWsConnected: (state, action: PayloadAction<boolean>) => {
      state.wsConnected = action.payload;
    },
    setWsRateUpdate: (state, action: PayloadAction<{ rates: any; timestamp: string }>) => {
      state.lastWsUpdate = action.payload.timestamp;
      // Mapear tasas WS al estado digital si vienen en el formato correcto
      const wsRates = action.payload.rates;
      if (wsRates && typeof wsRates === 'object') {
        Object.entries(wsRates).forEach(([code, rateData]: [string, any]) => {
          if (rateData && rateData.buy) {
            state.digital.byCode[code] = {
              ...state.digital.byCode[code],
              ...rateData,
              pair:      `${code}/BOB`,
              is_live:   true,
              timestamp: action.payload.timestamp,
            } as LiveRate;
          }
        });
      }
    },
    clearErrors: (state) => {
      state.digital.error    = null;
      state.predictions.error = null;
      state.manual.error     = null;
    },
  },
  extraReducers: (builder) => {
    // ── fetchLiveRate ──────────────────────────────────────────────────────
    builder
      .addCase(fetchLiveRate.pending, (state) => { state.digital.loading = true; })
      .addCase(fetchLiveRate.fulfilled, (state, action) => {
        state.digital.loading = false;
        state.digital.byCode[action.payload.currency] = action.payload.data;
        state.digital.lastFetch = new Date().toISOString();
      })
      .addCase(fetchLiveRate.rejected, (state, action) => {
        state.digital.loading = false;
        state.digital.error   = action.payload as string;
      });

    // ── fetchAllLiveRates ──────────────────────────────────────────────────
    builder
      .addCase(fetchAllLiveRates.pending, (state) => { state.digital.loading = true; })
      .addCase(fetchAllLiveRates.fulfilled, (state, action) => {
        state.digital.loading = false;
        action.payload.forEach(({ currency, data }) => {
          state.digital.byCode[currency] = data;
        });
        state.digital.lastFetch = new Date().toISOString();
      })
      .addCase(fetchAllLiveRates.rejected, (state, action) => {
        state.digital.loading = false;
        state.digital.error   = action.payload as string;
      });

    // ── fetchForecast ──────────────────────────────────────────────────────
    builder
      .addCase(fetchForecast.pending, (state) => { state.predictions.loading = true; })
      .addCase(fetchForecast.fulfilled, (state, action) => {
        state.predictions.loading = false;
        state.predictions.byPair[action.payload.pair] = action.payload.data;
      })
      .addCase(fetchForecast.rejected, (state, action) => {
        state.predictions.loading = false;
        state.predictions.error   = action.payload as string;
      });

    // ── fetchPredictionHealth ──────────────────────────────────────────────
    builder
      .addCase(fetchPredictionHealth.fulfilled, (state, action) => {
        state.predictions.health = action.payload;
      });

    // ── fetchManualRates ───────────────────────────────────────────────────
    builder
      .addCase(fetchManualRates.pending, (state) => { state.manual.loading = true; })
      .addCase(fetchManualRates.fulfilled, (state, action) => {
        state.manual.loading = false;
        state.manual.rates   = action.payload;
      })
      .addCase(fetchManualRates.rejected, (state, action) => {
        state.manual.loading = false;
        state.manual.error   = action.payload as string;
      });
  },
});

export const { setWsConnected, setWsRateUpdate, clearErrors } = ratesSlice.actions;

// ── Selectores ────────────────────────────────────────────────────────────────

export const selectDigitalRate  = (code: string)  => (state: { rates: RatesState }) => state.rates.digital.byCode[code] ?? null;
export const selectAllDigital               = (state: { rates: RatesState }) => state.rates.digital;
export const selectPrediction   = (pair: string) => (state: { rates: RatesState }) => state.rates.predictions.byPair[pair] ?? null;
export const selectAllPredictions           = (state: { rates: RatesState }) => state.rates.predictions;
export const selectManualRates              = (state: { rates: RatesState }) => state.rates.manual;
export const selectWsStatus                 = (state: { rates: RatesState }) => ({
  connected:   state.rates.wsConnected,
  lastUpdate:  state.rates.lastWsUpdate,
});

export default ratesSlice.reducer;
