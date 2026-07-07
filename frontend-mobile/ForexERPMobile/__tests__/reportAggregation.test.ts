/**
 * Tests del promedio ponderado real en la agregación de reportes diarios:
 *   avg_rate = total BOB / total unidades de divisa
 * (reemplaza al promedio móvil incorrecto (avg+rate)/2).
 */
import { describe, it, expect } from '@jest/globals';
import { aggregateDailyReport } from '../src/utils/reportAggregation';

describe('aggregateDailyReport', () => {
  it('devuelve [] sin transacciones', () => {
    expect(aggregateDailyReport([])).toEqual([]);
  });

  it('calcula promedio ponderado en compras (BUY: amount_from divisa, amount_to BOB)', () => {
    const txs = [
      // 100 USD a 6.96 → 696 BOB   ·   200 USD a 7.00 → 1400 BOB
      { transaction_type: 'BUY', currency_from: 'USD', amount_from: '100', amount_to: '696',  exchange_rate: '6.96' },
      { transaction_type: 'BUY', currency_from: 'USD', amount_from: '200', amount_to: '1400', exchange_rate: '7.00' },
    ];
    const [usd] = aggregateDailyReport(txs);

    expect(usd.currency).toBe('USD');
    expect(usd.transaction_count).toBe(2);
    expect(usd.total_buy).toBeCloseTo(2096, 5);
    // Ponderado: (696 + 1400) / (100 + 200) = 6.98666…  (NO (6.96+7.00)/2 tras seed 0)
    expect(usd.avg_rate).toBeCloseTo(2096 / 300, 6);
  });

  it('calcula promedio ponderado mezclando BUY y SELL (SELL: amount_from BOB, amount_to divisa)', () => {
    const txs = [
      { transaction_type: 'BUY',  currency_from: 'USD', amount_from: '100', amount_to: '696', exchange_rate: '6.96' },
      // La casa vende 50 USD y recibe 352.5 BOB (tasa 7.05)
      { transaction_type: 'SELL', currency_from: 'USD', amount_from: '352.5', amount_to: '50', exchange_rate: '7.05' },
    ];
    const [usd] = aggregateDailyReport(txs);

    expect(usd.total_buy).toBeCloseTo(696, 5);
    expect(usd.total_sell).toBeCloseTo(50, 5);
    expect(usd.transaction_count).toBe(2);
    // (696 + 352.5) BOB / (100 + 50) USD = 6.99
    expect(usd.avg_rate).toBeCloseTo(1048.5 / 150, 6);
  });

  it('agrupa por divisa usando currency_from (objeto o string)', () => {
    const txs = [
      { transaction_type: 'BUY', currency_from: { code: 'USD' }, amount_from: '100', amount_to: '696' },
      { transaction_type: 'BUY', currency_from: 'EUR',           amount_from: '100', amount_to: '800' },
    ];
    const report = aggregateDailyReport(txs);

    expect(report.map(r => r.currency).sort()).toEqual(['EUR', 'USD']);
    expect(report.find(r => r.currency === 'EUR')?.avg_rate).toBeCloseTo(8, 6);
  });

  it('sin unidades de divisa (denominador 0) el promedio queda en 0', () => {
    const txs = [
      { transaction_type: 'BUY', currency_from: 'USD', amount_from: '0', amount_to: '0' },
    ];
    const [usd] = aggregateDailyReport(txs);
    expect(usd.avg_rate).toBe(0);
  });
});
