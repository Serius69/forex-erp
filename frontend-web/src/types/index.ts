export interface User {
  id:                    number;
  username:              string;
  email:                 string;
  first_name:            string;
  last_name:             string;
  role:                  'ADMIN' | 'SUPERVISOR' | 'CASHIER';
  branch:                Branch | null;
  branch_id?:            number | null;
  is_active:             boolean;
  is_verified:           boolean;
  is_two_factor_enabled: boolean;
  date_joined?:          string;
  last_login?:           string | null;
}

export interface Branch {
  id: number;
  name: string;
  code: string;
  address: string;
  phone: string;
  is_active: boolean;
}

export interface Currency {
  id: number;
  code: string;
  name: string;
  symbol: string;
  /** Multiplicador de unidades. scale_factor=1000 → CLP/ARS (1 unidad del sistema = 1000 reales). */
  scale_factor: number;
}

export interface Transaction {
  id: number;
  transaction_number: string;
  transaction_type: 'BUY' | 'SELL';
  customer: Customer;
  currency_from: Currency;
  currency_to: Currency;
  amount_from: number;
  amount_to: number;
  exchange_rate: number;
  payment_method: string;
  payment_reference?: string;
  status: 'PENDING' | 'COMPLETED' | 'CANCELLED' | 'REVERSED';
  cashier: User;
  branch: Branch;
  notes?: string;
  created_at: string;
  updated_at: string;
}

export interface Customer {
  id: number;
  document_type: string;
  document_number: string;
  full_name: string;
  phone?: string;
  email?: string;
  address?: string;
  is_frequent: boolean;
  is_pep: boolean;
}

export interface ExchangeRate {
  id: number;
  currency_from: Currency;
  currency_to: Currency;
  official_rate: number;
  buy_rate: number;
  sell_rate: number;
  /** 'official' = tasa BCB regulada, 'parallel' = mercado paralelo boliviano */
  market_type: 'official' | 'parallel';
  source: string;
  valid_from: string;
  valid_until?: string;
}

export interface Inventory {
  id: number;
  currency: Currency;
  branch: Branch;
  physical_balance: number;
  digital_balance: number;
  minimum_stock: number;
  maximum_stock: number;
  weighted_average_cost: number;
  last_updated: string;
}

export interface Prediction {
  id: number;
  currency_pair: string;
  prediction_date: string;
  predicted_rate: number;
  predicted_buy_rate: number;
  predicted_sell_rate: number;
  confidence_lower: number;
  confidence_upper: number;
  confidence_score: number;
  model_type: string;
}

export interface Report {
  id: number;
  report_type: string;
  title: string;
  start_date: string;
  end_date: string;
  pdf_file?: string;
  excel_file?: string;
  generated_by: User;
  generated_at: string;
}

export interface Alert {
  id: number;
  type: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  title: string;
  message: string;
  is_resolved: boolean;
  created_at: string;
}