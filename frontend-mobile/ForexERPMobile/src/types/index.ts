// index.ts - Definición de tipos para la aplicación móvil Forex ERP
// ─── Auth ─────────────────────────────────────────────────────────────────────
export interface LoginCredentials {
  username: string;
  password: string;
  pin: string;
}

export interface AuthTokens {
  access: string;
  refresh: string;
}

export interface User {
  id: number;
  username: string;
  full_name: string;
  role: 'ADMIN' | 'SUPERVISOR' | 'CASHIER';
  branch: number | null;
}

// ─── Tasas ────────────────────────────────────────────────────────────────────
export interface CurrencyRate {
  buy: number;
  sell: number;
  official: number;
  spread: number;
}

export type RatesMap = Record<string, CurrencyRate>;

// ─── Predicciones ─────────────────────────────────────────────────────────────
export interface Prediction {
  id: number;
  currency_pair: string;
  prediction_date: string;
  predicted_buy_rate: number;
  predicted_sell_rate: number;
  confidence_score: number;
  model_used: string;
}

// ─── Transacciones ────────────────────────────────────────────────────────────
export type TransactionType = 'BUY' | 'SELL';
export type PaymentMethod = 'CASH' | 'TRANSFER' | 'QR';

export interface Customer {
  id: number;
  document_type: 'CI' | 'NIT' | 'PASSPORT';
  document_number: string;
  full_name: string;
  phone: string;
  email: string;
  is_frequent: boolean;
}

export interface Transaction {
  id: number;
  transaction_number: string;
  transaction_type: TransactionType;
  customer: Customer;
  currency_from: string;
  currency_to: string;
  amount_from: number;
  amount_to: number;
  exchange_rate: number;
  payment_method: PaymentMethod;
  notes: string;
  created_at: string;
}

export interface NewTransactionPayload {
  transaction_type: TransactionType;
  customer_id?: number;
  document_number: string;
  customer_name: string;
  currency_from: string;
  amount_from: number;
  exchange_rate: number;
  payment_method: PaymentMethod;
  notes?: string;
}

export interface DailySummary {
  transaction_count: number;
  total_buy: number;
  total_sell: number;
  total_profit: number;
}

// ─── Inventario ───────────────────────────────────────────────────────────────
export interface CurrencyInventory {
  id: number;
  currency: string;
  branch: number;
  physical_balance: number;
  digital_balance: number;
  total_balance: number;
  minimum_stock: number;
  maximum_stock: number;
  weighted_average_cost: number;
  needs_replenishment: boolean;
  last_updated: string;
}

// ─── Alertas ──────────────────────────────────────────────────────────────────
export type AlertSeverity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export interface Alert {
  id: number;
  type: string;
  severity: AlertSeverity;
  title: string;
  message: string;
  currency: string;
  branch: number;
  is_read: boolean;
  created_at: string;
}

// ─── Reportes ─────────────────────────────────────────────────────────────────
export interface ReportSummary {
  currency: string;
  total_buy: number;
  total_sell: number;
  avg_rate: number;
  transaction_count: number;
  profit: number;
}

// ─── Navegación ───────────────────────────────────────────────────────────────
export type RootStackParamList = {
  Login: undefined;
  Main: undefined;
};

export type BottomTabParamList = {
  Dashboard: undefined;
  Transaction: undefined;
  Inventory: undefined;
  Tarjetas: undefined;
  Reports: undefined;
  Alerts: undefined;
};
