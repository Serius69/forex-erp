"""
Backfill de TransactionProfitLedger + PnLDailySnapshot para transacciones
históricas cargadas con bulk_create (que bypassa el flujo que puebla el ledger).

Simula el WAC cronológicamente por (branch, divisa): cada BUY actualiza el WAC
promedio ponderado; cada SELL usa el WAC vigente en ESE momento como costo (no
el WAC actual, que sesgaría todo el histórico). fecha = fecha local de la tx.

Uso:
    python manage.py backfill_profit_ledger [--purge] [--dry-run]

--purge: borra el ledger y los snapshots existentes antes de recalcular
         (idempotente: sin --purge solo procesa tx sin fila en el ledger).
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

import zoneinfo

from django.core.management.base import BaseCommand
from django.db import transaction as db_tx
from django.db.models import Count, Sum

from analytics.services import _q, RATE_Q, PCT_Q

LA_PAZ = zoneinfo.ZoneInfo('America/La_Paz')

# profit_pct es DecimalField(8,4): |valor| < 10^4. Con costos ~0 el % explota.
PCT_MAX = Decimal('9999.9999')


def _pct_clamp(val: Decimal) -> Decimal:
    return max(-PCT_MAX, min(PCT_MAX, val))


class Command(BaseCommand):
    help = 'Recalcula TransactionProfitLedger y PnLDailySnapshot desde el histórico de transacciones'

    def add_arguments(self, parser):
        parser.add_argument('--purge', action='store_true',
                            help='Borrar ledger y snapshots antes de recalcular')
        parser.add_argument('--dry-run', action='store_true',
                            help='Solo reportar, sin escribir')

    def handle(self, *args, **opts):
        from analytics.models import TransactionProfitLedger, PnLDailySnapshot
        from capital.models import Gasto
        from transactions.models import Transaction

        purge, dry = opts['purge'], opts['dry_run']

        with db_tx.atomic():
            if purge and not dry:
                n1 = TransactionProfitLedger.objects.all().delete()[0]
                n2 = PnLDailySnapshot.objects.all().delete()[0]
                self.stdout.write(f'purge: {n1} filas ledger, {n2} snapshots')

            ya_registradas = set(
                TransactionProfitLedger.objects
                .filter(transaction_type__in=('BUY', 'SELL'))
                .values_list('transaction_id', flat=True)
            )

            qs = (
                Transaction.objects
                .filter(status='COMPLETED')
                .exclude(currency_from__code='BOB', currency_to__code='BOB')
                .select_related('currency_from', 'currency_to', 'branch')
                .order_by('created_at', 'id')
            )

            # Estado WAC corriente por (branch_id, code): [stock, wac_por_lote]
            estado = defaultdict(lambda: [Decimal('0'), None])
            nuevos = []

            for tx in qs.iterator(chunk_size=500):
                # Divisa extranjera y orientación (mismas reglas que ProfitEngine)
                if tx.currency_from.code != 'BOB':
                    foreign = tx.currency_from
                    amount_foreign = _q(tx.amount_from, RATE_Q)
                    amount_bob = _q(tx.amount_to)
                else:
                    foreign = tx.currency_to
                    amount_foreign = _q(tx.amount_to, RATE_Q)
                    amount_bob = _q(tx.amount_from)

                rate = _q(tx.exchange_rate, RATE_Q)
                scale = Decimal(str(foreign.scale_factor or 1))
                key = (tx.branch_id, foreign.code)
                stock, wac = estado[key]
                if wac is None:
                    wac = rate  # primer contacto: costo = tasa de la operación

                if tx.transaction_type == 'BUY':
                    nuevo_stock = stock + amount_foreign
                    if nuevo_stock > 0:
                        wac = _q((stock * wac + amount_foreign * rate) / nuevo_stock, RATE_Q)
                    estado[key] = [nuevo_stock, wac]
                    cost_bob = _q(amount_foreign * (rate / scale))
                    profit_bob = _q(0)
                    profit_pct = _q(0, PCT_Q)
                    spread_bob = _q(0, RATE_Q)
                elif tx.transaction_type == 'SELL':
                    estado[key] = [max(Decimal('0'), stock - amount_foreign), wac]
                    wac_unit = _q(wac / scale, RATE_Q)
                    sell_unit = _q(rate / scale, RATE_Q)
                    cost_bob = _q(amount_foreign * wac_unit)
                    profit_bob = _q(amount_bob - cost_bob)
                    spread_bob = _q(sell_unit - wac_unit, RATE_Q)
                    profit_pct = (_pct_clamp(_q(profit_bob / cost_bob * 100, PCT_Q))
                                  if cost_bob != 0 else _q(0, PCT_Q))
                else:
                    continue  # otros tipos no aplican al ledger BUY/SELL

                if tx.id in ya_registradas:
                    continue  # ya estaba (pero su BUY/SELL sí actualizó el WAC simulado)

                nuevos.append(TransactionProfitLedger(
                    transaction=tx,
                    transaction_type=tx.transaction_type,
                    currency_code=foreign.code,
                    branch=tx.branch,
                    fecha=tx.created_at.astimezone(LA_PAZ).date(),
                    amount_foreign=amount_foreign,
                    exchange_rate=rate,
                    amount_bob=amount_bob,
                    wac_at_transaction=wac,
                    wac_after_transaction=wac,
                    cost_bob=cost_bob,
                    profit_bob=profit_bob,
                    profit_pct=profit_pct,
                    spread_bob=spread_bob,
                ))

            self.stdout.write(f'tx a registrar en ledger: {len(nuevos)}')
            if dry:
                return

            TransactionProfitLedger.objects.bulk_create(nuevos, batch_size=500)

            # ── Reconstruir snapshots diarios por (fecha, branch) ────────────
            # Unión ledger ∪ gastos: un día con gastos pero sin transacciones
            # también necesita snapshot. order_by() limpia el ordering default
            # que contaminaría el DISTINCT.
            pares = set(
                TransactionProfitLedger.objects
                .order_by().values_list('fecha', 'branch_id').distinct()
            ) | set(
                Gasto.objects
                .order_by().values_list('fecha', 'branch_id').distinct()
            )
            n_snap = 0
            for fecha, branch_id in pares:
                ventas = (
                    TransactionProfitLedger.objects
                    .filter(branch_id=branch_id, fecha=fecha, transaction_type='SELL')
                    .aggregate(count=Count('id'), ingreso=Sum('amount_bob'),
                               costo=Sum('cost_bob'), ganancia=Sum('profit_bob'))
                )
                compras = (
                    TransactionProfitLedger.objects
                    .filter(branch_id=branch_id, fecha=fecha, transaction_type='BUY')
                    .aggregate(count=Count('id'), inversion=Sum('amount_bob'))
                )
                gastos = (
                    Gasto.objects.filter(branch_id=branch_id, fecha=fecha)
                    .aggregate(total=Sum('monto_bob'))['total'] or Decimal('0')
                )
                ingreso = _q(ventas['ingreso'] or 0)
                bruta = _q(ventas['ganancia'] or 0)
                neta = _q(bruta - _q(gastos))
                margen = (_q(neta / ingreso * 100, PCT_Q)
                          if ingreso != 0 else _q(0, PCT_Q))
                PnLDailySnapshot.objects.update_or_create(
                    fecha=fecha, branch_id=branch_id,
                    defaults={
                        'num_ventas': ventas['count'] or 0,
                        'ingreso_ventas_bob': ingreso,
                        'costo_ventas_bob': _q(ventas['costo'] or 0),
                        'ganancia_bruta_bob': bruta,
                        'num_compras': compras['count'] or 0,
                        'inversion_compras_bob': _q(compras['inversion'] or 0),
                        'gastos_operativos_bob': _q(gastos),
                        'ganancia_neta_bob': neta,
                        'margen_neto_pct': margen,
                    },
                )
                n_snap += 1

            self.stdout.write(self.style.SUCCESS(
                f'ledger: +{len(nuevos)} filas · snapshots reconstruidos: {n_snap}'
            ))
