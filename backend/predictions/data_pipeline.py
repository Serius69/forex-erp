"""
ForexDataPipeline — ingesta consolidada y feature engineering para todos los modelos ML.

Responsabilidades:
  - Carga datos de TrainingData con ventana de 3 años (evita cargar toda la tabla)
  - Normaliza timestamps a UTC y hace resample horario
  - Capea outliers por IQR (no elimina, preserva continuidad)
  - Genera >40 features técnicos, de calendario y macroeconómicos
  - Devuelve DataFrame limpio listo para cualquier modelo
"""
import numpy as np
import pandas as pd
from datetime import timedelta
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

# Países de referencia para festivos por divisa
_HOLIDAY_COUNTRIES = {
    'USD': 'US', 'EUR': 'DE', 'BRL': 'BR',
    'ARS': 'AR', 'PEN': 'PE', 'CLP': 'CL', 'BOB': 'BO',
}


class ForexDataPipeline:
    """Pipeline de features compartido por todos los modelos de pronóstico."""

    LOOKBACK_YEARS   = 3
    MIN_ROWS         = 100
    OUTLIER_IQR_MULT = 3.0

    # ── Entrada pública ────────────────────────────────────────────────────────

    def build(self, currency_pair: str, start_date=None) -> pd.DataFrame:
        """
        Retorna DataFrame con índice DatetimeIndex UTC, frecuencia horaria.
        Columnas incluyen 'rate' + todos los features técnicos/calendario/macro.
        """
        df = self._load(currency_pair, start_date)
        df = self._normalize_timestamps(df)
        df = self._resample_hourly(df)
        df = self._cap_outliers(df)
        df = self._add_technical(df)
        df = self._add_calendar(df, currency_pair)
        df = self._add_macro(df)
        df = df.dropna(subset=['rate'])
        logger.info(
            "pipeline.build pair=%s rows=%d features=%d",
            currency_pair, len(df), len(df.columns),
        )
        return df

    # ── Carga ──────────────────────────────────────────────────────────────────

    def _load(self, currency_pair: str, start_date=None) -> pd.DataFrame:
        from predictions.models import TrainingData

        cutoff = start_date or (timezone.now() - timedelta(days=365 * self.LOOKBACK_YEARS))
        qs = (
            TrainingData.objects
            .filter(currency_pair=currency_pair, date__gte=cutoff)
            .order_by('date')
            .values('date', 'rate', 'volume',
                    'international_rate', 'interest_rate',
                    'inflation_rate', 'oil_price')
        )
        df = pd.DataFrame(list(qs))
        if df.empty or len(df) < self.MIN_ROWS:
            raise ValueError(
                f"Datos insuficientes para {currency_pair}: "
                f"necesita {self.MIN_ROWS}, tiene {len(df)}"
            )
        df['rate'] = pd.to_numeric(df['rate'], errors='coerce')
        return df

    # ── Normalización temporal ─────────────────────────────────────────────────

    def _normalize_timestamps(self, df: pd.DataFrame) -> pd.DataFrame:
        df['date'] = pd.to_datetime(df['date'], utc=True)
        df = df.set_index('date').sort_index()
        df = df[~df.index.duplicated(keep='last')]
        return df

    def _resample_hourly(self, df: pd.DataFrame) -> pd.DataFrame:
        """Resample a frecuencia 1H; forward-fill rate, interpolar columnas dispersas."""
        df = df.resample('1h').last()
        df['rate'] = df['rate'].ffill()
        sparse_cols = ['international_rate', 'oil_price', 'interest_rate', 'inflation_rate']
        for col in sparse_cols:
            if col in df.columns:
                df[col] = df[col].ffill().bfill()
        if 'volume' in df.columns:
            df['volume'] = df['volume'].fillna(0)
        return df

    # ── Outliers ───────────────────────────────────────────────────────────────

    def _cap_outliers(self, df: pd.DataFrame) -> pd.DataFrame:
        q1, q3 = df['rate'].quantile(0.25), df['rate'].quantile(0.75)
        iqr = q3 - q1
        df['rate'] = df['rate'].clip(
            lower=q1 - self.OUTLIER_IQR_MULT * iqr,
            upper=q3 + self.OUTLIER_IQR_MULT * iqr,
        )
        return df

    # ── Features técnicos ─────────────────────────────────────────────────────

    def _add_technical(self, df: pd.DataFrame) -> pd.DataFrame:
        r = df['rate']

        # Medias móviles simples y exponenciales
        for w in (7, 14, 30, 90):
            df[f'ma_{w}'] = r.rolling(w, min_periods=1).mean()
        for s in (12, 26):
            df[f'ema_{s}'] = r.ewm(span=s, adjust=False).mean()

        # MACD
        df['macd']        = df['ema_12'] - df['ema_26']
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist']   = df['macd'] - df['macd_signal']

        # RSI 14
        df['rsi'] = _rsi(r, 14)

        # Bollinger Bands (20 períodos, 2σ)
        bb_mid = r.rolling(20, min_periods=1).mean()
        bb_std = r.rolling(20, min_periods=1).std().fillna(0)
        df['bb_upper']  = bb_mid + 2 * bb_std
        df['bb_middle'] = bb_mid
        df['bb_lower']  = bb_mid - 2 * bb_std
        df['bb_width']  = (df['bb_upper'] - df['bb_lower']) / bb_mid.replace(0, np.nan)
        df['bb_pct']    = (
            (r - df['bb_lower']) /
            (df['bb_upper'] - df['bb_lower']).replace(0, np.nan)
        )

        # ATR — proxy usando ventana 24h (máximo–mínimo + distancia al cierre previo)
        high = r.rolling(24, min_periods=1).max()
        low  = r.rolling(24, min_periods=1).min()
        prev = r.shift(1)
        tr   = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
        df['atr_14'] = tr.rolling(14, min_periods=1).mean()

        # Volatilidad rolling
        for w in (7, 14, 30):
            df[f'volatility_{w}'] = r.rolling(w, min_periods=1).std().fillna(0)

        # Retornos porcentuales
        for p in (1, 7, 30):
            df[f'pct_change_{p}'] = r.pct_change(p).fillna(0)

        # Lag features (claves para XGBoost)
        for lag in (1, 2, 3, 6, 12, 24, 48, 168):
            df[f'lag_{lag}'] = r.shift(lag)

        return df

    # ── Features de calendario ────────────────────────────────────────────────

    def _add_calendar(self, df: pd.DataFrame, currency_pair: str) -> pd.DataFrame:
        idx = df.index
        df['hour']          = idx.hour
        df['day_of_week']   = idx.dayofweek
        df['day_of_month']  = idx.day
        df['month']         = idx.month
        df['quarter']       = idx.quarter
        df['is_weekend']    = (idx.dayofweek >= 5).astype(int)

        # Sesiones del mercado forex (UTC)
        df['is_sydney_session']   = ((idx.hour >= 22) | (idx.hour < 7)).astype(int)
        df['is_london_session']   = ((idx.hour >= 8)  & (idx.hour < 16)).astype(int)
        df['is_new_york_session'] = ((idx.hour >= 13) & (idx.hour < 22)).astype(int)
        df['is_overlap_session']  = ((idx.hour >= 13) & (idx.hour < 16)).astype(int)

        # Festivos del país base
        base_currency = currency_pair.split('/')[0]
        country_code  = _HOLIDAY_COUNTRIES.get(base_currency, 'US')
        try:
            import holidays
            country_hols = holidays.country_holidays(country_code)
            df['is_holiday'] = [int(d in country_hols) for d in idx.date]
        except ImportError:
            df['is_holiday'] = 0

        return df

    # ── Features macroeconómicos ──────────────────────────────────────────────

    def _add_macro(self, df: pd.DataFrame) -> pd.DataFrame:
        for col in ('international_rate', 'interest_rate', 'inflation_rate', 'oil_price'):
            if col in df.columns:
                df[col] = df[col].ffill().bfill().fillna(0)
            else:
                df[col] = 0.0
        return df


# ── Funciones auxiliares ───────────────────────────────────────────────────────

def _rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff()
    gain  = delta.clip(lower=0).rolling(period, min_periods=1).mean()
    loss  = (-delta.clip(upper=0)).rolling(period, min_periods=1).mean()
    rs    = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)
