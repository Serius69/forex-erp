// Shared types for the Rates module (extracted from Rates.tsx).

export interface RateCurrency {
  id?:           number;
  code:          string;
  name?:         string;
  scale_factor?: number;
}

export interface ExchangeRate {
  id:                 number;
  currency_from?:     RateCurrency;
  currency_to?:       RateCurrency;
  buy_rate:           string;
  sell_rate:          string;
  official_rate?:     string;
  spread_percentage?: string;
  confidence?:        string;
  source_method:      string;
  source_url?:        string | null;
  fetched_at?:        string | null;
  market_type?:       string;
  is_primary?:        boolean;
  is_validated?:      boolean;
  valid_until?:       string | null;
}

// Live FX engine payload (GET /rates/exchange-rates/live/).
export interface LiveRate {
  pair:        string;
  buy:         number;
  sell:        number;
  spread:      number;
  spread_pct:  number;
  source:      string;
  source_url:  string | null;
  confidence:  number;
  timestamp:   string;
  is_live:     boolean;
  anomalies:   { type: string; severity: string; message: string }[];
}
