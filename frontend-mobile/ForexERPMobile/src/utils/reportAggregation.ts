/**
 * reportAggregation — agrupación de transacciones diarias por divisa.
 *
 * Semántica de montos (moneda base BOB):
 *   • BUY : el cliente entrega divisa   → amount_from = divisa, amount_to = BOB.
 *   • SELL: la casa vende divisa        → amount_from = BOB,    amount_to = divisa.
 *
 * El tipo de cambio promedio es un promedio PONDERADO real:
 *   avg_rate = total BOB movido / total unidades de divisa movidas
 * (no un promedio móvil de tasas, que sobre-pondera las últimas operaciones).
 */
import { ReportSummary } from '../types';

export function aggregateDailyReport(txs: any[]): ReportSummary[] {
  const map:      Record<string, ReportSummary> = {};
  const bobTotal: Record<string, number>        = {};   // numerador   (BOB)
  const curTotal: Record<string, number>        = {};   // denominador (divisa)

  txs.forEach((tx: any) => {
    const cur = tx.currency_from?.code ?? tx.currency_from ?? 'USD';
    if (!map[cur]) {
      map[cur]      = { currency: cur, total_buy: 0, total_sell: 0, avg_rate: 0, transaction_count: 0, profit: 0 };
      bobTotal[cur] = 0;
      curTotal[cur] = 0;
    }

    const amountFrom = parseFloat(tx.amount_from) || 0;
    const amountTo   = parseFloat(tx.amount_to)   || 0;

    if (tx.transaction_type === 'BUY') {
      // Cliente entrega divisa: amount_from = divisa, amount_to = BOB
      map[cur].total_buy += amountTo;
      bobTotal[cur]      += amountTo;
      curTotal[cur]      += amountFrom;
    } else {
      // Casa vende divisa: amount_from = BOB, amount_to = divisa
      map[cur].total_sell += amountTo;
      bobTotal[cur]       += amountFrom;
      curTotal[cur]       += amountTo;
    }

    map[cur].transaction_count += 1;
    map[cur].avg_rate = curTotal[cur] > 0 ? bobTotal[cur] / curTotal[cur] : 0;
    map[cur].profit   = map[cur].total_sell - map[cur].total_buy;
  });

  return Object.values(map);
}
