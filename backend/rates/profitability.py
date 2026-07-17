# rates/profitability.py
"""
Análisis de rentabilidad por operación y agregaciones por dimensiones:
par de divisas, cajero, horario y segmento de cliente.

Fórmula de margen bruto:
    margen_bruto = (tasa_operada - tasa_paralela) × monto

Donde tasa_paralela es la tasa paralela en el momento de la transacción
(capturada en parallel_rate_at_creation o recuperada como mejor estimación).
"""
import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.core.cache import cache
from django.db.models import Avg, Sum, Count, F, Q
from django.utils import timezone

log = logging.getLogger('rates.profitability')

_CACHE_KEY  = 'profitability_analysis:{company_id}:{period}'
_CACHE_TTL  = 300   # 5 minutos


@dataclass
class ProfitabilityReport:
    period_start:          str
    period_end:            str
    total_transactions:    int
    total_volume_foreign:  Decimal
    total_margin_bob:      Decimal
    avg_margin_pct:        Decimal
    by_currency_pair:      list[dict] = field(default_factory=list)
    by_cashier:            list[dict] = field(default_factory=list)
    by_hour:               list[dict] = field(default_factory=list)
    by_customer_segment:   list[dict] = field(default_factory=list)
    alerts:                list[str]  = field(default_factory=list)


class ProfitabilityAnalyzer:
    """
    Calcula la rentabilidad de transacciones de cambio.

    Uso:
        analyzer = ProfitabilityAnalyzer()
        report   = analyzer.analyze(
            company_id=1,
            date_from=datetime(2026, 4, 1),
            date_to=datetime(2026, 4, 30),
            min_margin_threshold_bob=50,   # alerta si margen < Bs 50
        )
    """

    # ── Margen de una transacción individual ──────────────────────────────────

    @staticmethod
    def compute_transaction_margin(
        exchange_rate:   Decimal,
        parallel_rate:   Decimal,
        amount_from:     int,
        transaction_type: str,    # BUY | SELL
        currency_from:   str,
        currency_to:     str,
    ) -> Decimal:
        """
        Calcula el margen bruto en BOB de una transacción.

        BUY (empresa compra divisa): gana si paga menos BOB que la paralela
            margen = (paralela - tasa_operada) × amount_from (en divisa)
        SELL (empresa vende divisa): gana si cobra más BOB que la paralela
            margen = (tasa_operada - paralela) × amount_from (en divisa)
        """
        if not parallel_rate or parallel_rate == 0:
            return Decimal('0')
        if transaction_type == 'BUY':
            # Pagamos amount_from divisas → recibimos en BOB
            if currency_to == 'BOB':
                # amount_from en divisa extranjera; amount_to en BOB
                margen = (parallel_rate - exchange_rate) * amount_from
            else:
                margen = Decimal('0')
        else:
            # Vendemos amount_from divisas → entregamos en BOB al cliente
            if currency_from != 'BOB':
                margen = (exchange_rate - parallel_rate) * amount_from
            else:
                margen = Decimal('0')

        return margen.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # ── Análisis agregado ─────────────────────────────────────────────────────

    def analyze(
        self,
        company_id: int,
        date_from,
        date_to,
        branch_id:              Optional[int] = None,
        min_margin_threshold:   Decimal = Decimal('50'),  # BOB por TX
    ) -> ProfitabilityReport:
        """
        Genera el reporte de rentabilidad para el período dado.
        Usa caché de 5 minutos.
        """
        cache_key = _CACHE_KEY.format(
            company_id=company_id,
            period=f'{date_from:%Y%m%d}-{date_to:%Y%m%d}-{branch_id or "all"}',
        )
        cached = cache.get(cache_key)
        if cached:
            return ProfitabilityReport(**cached)

        report = self._compute(
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            branch_id=branch_id,
            min_margin_threshold=min_margin_threshold,
        )
        try:
            cache.set(cache_key, report.__dict__, _CACHE_TTL)
        except Exception:
            pass
        return report

    def _compute(self, company_id, date_from, date_to, branch_id, min_margin_threshold) -> ProfitabilityReport:
        from transactions.models import Transaction
        from rates.models import ExchangeRate

        # Base queryset: transacciones COMPLETADAS en el período
        qs = Transaction.objects.filter(
            branch__company_id=company_id,
            status='COMPLETED',
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
        ).select_related('currency_from', 'currency_to', 'cashier', 'customer')

        if branch_id:
            qs = qs.filter(branch_id=branch_id)

        # Recopilar datos y calcular márgenes
        total_vol      = Decimal('0')
        total_margin   = Decimal('0')
        alerts         = []
        by_pair:   dict = {}
        by_cashier:dict = {}
        by_hour:   dict = {h: {'hour': h, 'count': 0, 'margin_bob': Decimal('0')} for h in range(24)}
        by_segment:dict = {'FREQUENT': {'count': 0, 'margin': Decimal('0')},
                           'REGULAR':  {'count': 0, 'margin': Decimal('0')},
                           'PEP':      {'count': 0, 'margin': Decimal('0')}}
        tx_count = 0

        # Cache de tasas paralelas por fecha/moneda para evitar N+1
        parallel_cache: dict[tuple, Decimal] = {}

        for tx in qs.iterator(chunk_size=500):
            tx_count += 1
            parallel_rate = tx.parallel_rate_at_creation

            if not parallel_rate:
                # Buscar la tasa paralela más cercana al momento de la TX
                key = (tx.currency_from.code, tx.created_at.date())
                if key not in parallel_cache:
                    er = (
                        ExchangeRate.objects
                        .filter(
                            currency_from__code=tx.currency_from.code,
                            currency_to__is_base_currency=True,
                            market_type__in=('paralelo_digital', 'paralelo_fisico_empresa'),
                            valid_from__lte=tx.created_at,
                        )
                        .order_by('-valid_from')
                        .values('avg_rate', 'buy_rate', 'sell_rate')
                        .first()
                    )
                    if er:
                        parallel_cache[key] = er['avg_rate'] or (er['buy_rate'] + er['sell_rate']) / 2
                    else:
                        parallel_cache[key] = None
                parallel_rate = parallel_cache[key]

            if not parallel_rate:
                continue

            margen = self.compute_transaction_margin(
                exchange_rate=tx.exchange_rate,
                parallel_rate=parallel_rate,
                amount_from=tx.amount_from,
                transaction_type=tx.transaction_type,
                currency_from=tx.currency_from.code,
                currency_to=tx.currency_to.code,
            )

            total_vol    += tx.amount_from
            total_margin += margen

            # Alerta de margen bajo
            if margen < min_margin_threshold:
                alerts.append(
                    f'TX {tx.transaction_number}: margen Bs {margen:.2f} < umbral Bs {min_margin_threshold}'
                )

            # Por par de divisas
            pair_key = f'{tx.currency_from.code}/{tx.currency_to.code}'
            if pair_key not in by_pair:
                by_pair[pair_key] = {'pair': pair_key, 'count': 0, 'volume': Decimal('0'), 'margin_bob': Decimal('0')}
            by_pair[pair_key]['count']      += 1
            by_pair[pair_key]['volume']     += tx.amount_from
            by_pair[pair_key]['margin_bob'] += margen

            # Por cajero
            cashier_key = str(tx.cashier_id)
            if cashier_key not in by_cashier:
                by_cashier[cashier_key] = {
                    'cashier_id':   tx.cashier_id,
                    'cashier_name': str(tx.cashier),
                    'count':        0,
                    'margin_bob':   Decimal('0'),
                }
            by_cashier[cashier_key]['count']      += 1
            by_cashier[cashier_key]['margin_bob'] += margen

            # Por hora
            h = tx.created_at.hour
            by_hour[h]['count']      += 1
            by_hour[h]['margin_bob'] += margen

            # Por segmento de cliente
            if tx.customer and tx.customer.is_pep:
                seg = 'PEP'
            elif tx.customer and tx.customer.is_frequent:
                seg = 'FREQUENT'
            else:
                seg = 'REGULAR'
            by_segment[seg]['count']  += 1
            by_segment[seg]['margin'] += margen

        avg_margin_pct = Decimal('0')
        if total_vol > 0:
            avg_margin_pct = (total_margin / total_vol * 100).quantize(Decimal('0.0001'))

        # Serializar Decimals para el cache
        def _d(v):
            return str(v) if isinstance(v, Decimal) else v

        return ProfitabilityReport(
            period_start=str(date_from),
            period_end=str(date_to),
            total_transactions=tx_count,
            total_volume_foreign=total_vol,
            total_margin_bob=total_margin,
            avg_margin_pct=avg_margin_pct,
            by_currency_pair=[
                {k: _d(v) for k, v in d.items()} for d in sorted(
                    by_pair.values(), key=lambda x: float(str(x['margin_bob'])), reverse=True
                )
            ],
            by_cashier=[
                {k: _d(v) for k, v in d.items()} for d in sorted(
                    by_cashier.values(), key=lambda x: float(str(x['margin_bob'])), reverse=True
                )
            ],
            by_hour=[
                {k: _d(v) for k, v in d.items()} for d in by_hour.values()
            ],
            by_customer_segment=[
                {'segment': seg, 'count': d['count'], 'margin_bob': _d(d['margin'])}
                for seg, d in by_segment.items()
            ],
            alerts=alerts[:50],  # limitar a 50 alertas en el reporte
        )
