# analytics/services.py
"""
Motor analítico financiero — Kapitalya Casa de Cambio.

SERVICIOS:
  ProfitEngine    → P&L real por transacción (WAC-based)
  ExposureService → Exposición al riesgo de mercado por divisa
  SpreadService   → Análisis de spreads y spreads históricos
  PnLService      → Aggregados diarios y series de tiempo
  DecisionEngine  → Recomendaciones BUY/SELL/HOLD basadas en reglas financieras

PRINCIPIOS:
  - Precisión Decimal en todas las operaciones
  - Thread-safe: operaciones críticas dentro de atomic()
  - Fire-and-forget para WebSocket (nunca propaga excepciones)
  - Separación estricta lectura/escritura
"""
import logging
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction as db_transaction
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from datetime import date, timedelta

log = logging.getLogger('analytics')

# ── Cuantizadores ──────────────────────────────────────────────────────────────
MONEY_Q   = Decimal('0.01')
RATE_Q    = Decimal('0.0001')
PCT_Q     = Decimal('0.0001')


def _q(val, q=MONEY_Q) -> Decimal:
    return Decimal(str(val or 0)).quantize(q, rounding=ROUND_HALF_UP)


# ─────────────────────────────────────────────────────────────────────────────
# ProfitEngine — P&L real por transacción usando WAC
# ─────────────────────────────────────────────────────────────────────────────

class ProfitEngine:
    """
    Registra la ganancia real de cada transacción usando Weighted Average Cost.

    CUÁNDO LLAMAR:
      - Siempre DESPUÉS de _update_inventory() (WAC ya actualizado para BUY).
      - Para SELL: WAC es el del inventario antes de la venta (no cambia al vender).
      - Para BUY:  WAC es el nuevo WAC resultante de agregar al inventario.
      - Llamar desde apply_transaction_effects() para atomicidad.

    Para reversas: llamar record_reversal_profit(original_transaction).
    """

    @staticmethod
    def record_transaction_profit(transaction) -> 'TransactionProfitLedger | None':
        """
        Registra el P&L de la transacción en TransactionProfitLedger.
        Devuelve None si ya existe un registro o si la transacción no aplica.
        """
        from .models import TransactionProfitLedger
        from inventory.models import CurrencyInventory

        # Idempotencia: no crear duplicados para el mismo tipo (BUY/SELL ya registrado)
        if TransactionProfitLedger.objects.filter(
            transaction=transaction,
            transaction_type__in=('BUY', 'SELL'),
        ).exists():
            return None

        # Solo transacciones completadas que involucren divisa extranjera
        if transaction.status != 'COMPLETED':
            return None
        if (transaction.currency_from.code == 'BOB'
                and transaction.currency_to.code == 'BOB'):
            return None

        # Determinar la divisa extranjera involucrada
        if transaction.transaction_type == 'BUY':
            # Casa compra divisa_from (extranjera), paga divisa_to (BOB)
            foreign_currency = transaction.currency_from
            amount_foreign   = _q(transaction.amount_from, RATE_Q)
            amount_bob       = _q(transaction.amount_to)
            exchange_rate    = _q(transaction.exchange_rate, RATE_Q)
        else:
            # Casa vende divisa_from (extranjera), recibe divisa_to (BOB) — OR viceversa
            # La divisa extranjera es la que NO es BOB
            if transaction.currency_from.code != 'BOB':
                foreign_currency = transaction.currency_from
                amount_foreign   = _q(transaction.amount_from, RATE_Q)
                amount_bob       = _q(transaction.amount_to)
                exchange_rate    = _q(transaction.exchange_rate, RATE_Q)
            else:
                foreign_currency = transaction.currency_to
                amount_foreign   = _q(transaction.amount_to, RATE_Q)
                amount_bob       = _q(transaction.amount_from)
                exchange_rate    = _q(transaction.exchange_rate, RATE_Q)

        # Leer WAC actual del inventario
        try:
            inv = CurrencyInventory.objects.get(
                currency=foreign_currency,
                branch=transaction.branch,
            )
            current_wac = _q(inv.weighted_average_cost, RATE_Q)
        except CurrencyInventory.DoesNotExist:
            current_wac = exchange_rate

        scale = Decimal(str(foreign_currency.scale_factor or 1))

        if transaction.transaction_type == 'BUY':
            # WAC antes = wac que había (lo necesitaríamos antes del add_currency, ya actualizado)
            # Para BUY: wac_at es el nuevo WAC (lo que tenemos ahora = post-BUY)
            # wac_before no lo sabemos exactamente aquí, pero registramos el post-BUY WAC
            wac_at    = current_wac   # WAC después de agregar (resultado)
            wac_after = current_wac
            # Costo de la compra = lo que pagamos
            cost_bob  = _q(amount_foreign * (exchange_rate / scale))
            profit_bob = _q(0)
            profit_pct = _q(0)
            spread_bob = _q(0)
        else:
            # SELL: WAC = costo unitario de lo que vendemos
            # exchange_rate está en BOB / lote (ya normalizado por transactions)
            # sell_rate_unit = exchange_rate / scale
            sell_rate_unit = _q(exchange_rate / scale, RATE_Q)
            wac_unit       = _q(current_wac / scale, RATE_Q)

            wac_at    = current_wac
            wac_after = current_wac  # WAC no cambia en SELL

            # Costo de la mercancía vendida (base WAC)
            cost_bob  = _q(amount_foreign * wac_unit)
            # Ingreso por la venta
            profit_bob = _q(amount_bob - cost_bob)
            spread_bob = _q(sell_rate_unit - wac_unit, RATE_Q)
            profit_pct = (
                _q(profit_bob / cost_bob * 100, PCT_Q)
                if cost_bob != 0 else _q(0, PCT_Q)
            )

        ledger = TransactionProfitLedger.objects.create(
            transaction          = transaction,
            transaction_type     = transaction.transaction_type,
            currency_code        = foreign_currency.code,
            branch               = transaction.branch,
            fecha                = timezone.localdate(),
            amount_foreign       = amount_foreign,
            exchange_rate        = exchange_rate,
            amount_bob           = amount_bob,
            wac_at_transaction   = wac_at,
            wac_after_transaction= wac_after,
            cost_bob             = cost_bob,
            profit_bob           = profit_bob,
            profit_pct           = profit_pct,
            spread_bob           = spread_bob,
        )

        log.info(
            'PROFIT_LEDGER tx=%s type=%s %s amount=%.4f profit=Bs.%.2f spread=%.4f',
            transaction.transaction_number,
            transaction.transaction_type,
            foreign_currency.code,
            float(amount_foreign),
            float(profit_bob),
            float(spread_bob),
        )

        # Invalidar/actualizar el snapshot P&L del día
        PnLService.recalcular_snapshot_hoy(transaction.branch)

        return ledger

    @staticmethod
    def record_reversal_profit(original_transaction) -> 'TransactionProfitLedger | None':
        """
        Registra la compensación P&L de una reversa.
        Crea un registro con profit_bob = -profit_original (anula el efecto).
        """
        from .models import TransactionProfitLedger

        try:
            original_ledger = TransactionProfitLedger.objects.get(
                transaction=original_transaction,
            )
        except TransactionProfitLedger.DoesNotExist:
            log.warning(
                'REVERSAL_PROFIT_SKIP no ledger for tx=%s',
                getattr(original_transaction, 'transaction_number', '?'),
            )
            return None

        # La reversa anula el P&L original
        reversal = TransactionProfitLedger.objects.create(
            transaction          = original_transaction,  # no tiene nueva tx, apunta a original
            transaction_type     = 'REVERSAL',
            currency_code        = original_ledger.currency_code,
            branch               = original_ledger.branch,
            fecha                = timezone.localdate(),
            amount_foreign       = original_ledger.amount_foreign,
            exchange_rate        = original_ledger.exchange_rate,
            amount_bob           = -original_ledger.amount_bob,
            wac_at_transaction   = original_ledger.wac_at_transaction,
            wac_after_transaction= original_ledger.wac_after_transaction,
            cost_bob             = -original_ledger.cost_bob,
            profit_bob           = -original_ledger.profit_bob,
            profit_pct           = -original_ledger.profit_pct,
            spread_bob           = original_ledger.spread_bob,
        )

        PnLService.recalcular_snapshot_hoy(original_transaction.branch)
        return reversal


# ─────────────────────────────────────────────────────────────────────────────
# PnLService — Agregados diarios y series de tiempo
# ─────────────────────────────────────────────────────────────────────────────

class PnLService:

    @staticmethod
    def recalcular_snapshot_hoy(branch) -> 'PnLDailySnapshot':
        """
        Recalcula el snapshot P&L del día para una sucursal.
        Atómico: update_or_create con select_for_update.
        """
        from .models import TransactionProfitLedger, PnLDailySnapshot
        from capital.models import Gasto

        hoy = timezone.localdate()

        with db_transaction.atomic():
            # Ventas del día
            ventas_agg = (
                TransactionProfitLedger.objects
                .filter(branch=branch, fecha=hoy, transaction_type='SELL')
                .aggregate(
                    count=Count('id'),
                    ingreso=Sum('amount_bob'),
                    costo=Sum('cost_bob'),
                    ganancia=Sum('profit_bob'),
                )
            )
            # Compras del día
            compras_agg = (
                TransactionProfitLedger.objects
                .filter(branch=branch, fecha=hoy, transaction_type='BUY')
                .aggregate(count=Count('id'), inversion=Sum('amount_bob'))
            )
            # Gastos operativos del día
            gastos_total = (
                Gasto.objects
                .filter(branch=branch, fecha=hoy)
                .aggregate(total=Sum('monto_bob'))['total'] or Decimal('0')
            )

            ingreso_ventas   = _q(ventas_agg['ingreso']  or 0)
            costo_ventas     = _q(ventas_agg['costo']    or 0)
            ganancia_bruta   = _q(ventas_agg['ganancia'] or 0)
            gastos_op        = _q(gastos_total)
            ganancia_neta    = _q(ganancia_bruta - gastos_op)
            margen_pct = (
                _q(ganancia_neta / ingreso_ventas * 100, PCT_Q)
                if ingreso_ventas != 0 else _q(0, PCT_Q)
            )

            snap, _ = PnLDailySnapshot.objects.update_or_create(
                fecha=hoy, branch=branch,
                defaults={
                    'num_ventas':             ventas_agg['count'] or 0,
                    'ingreso_ventas_bob':      ingreso_ventas,
                    'costo_ventas_bob':        costo_ventas,
                    'ganancia_bruta_bob':      ganancia_bruta,
                    'num_compras':             compras_agg['count'] or 0,
                    'inversion_compras_bob':   _q(compras_agg['inversion'] or 0),
                    'gastos_operativos_bob':   gastos_op,
                    'ganancia_neta_bob':       ganancia_neta,
                    'margen_neto_pct':         margen_pct,
                }
            )

        return snap

    @staticmethod
    def series_pnl(branch, date_from: date, date_to: date) -> list:
        """Serie temporal de P&L diario para gráficos."""
        from .models import PnLDailySnapshot

        return list(
            PnLDailySnapshot.objects
            .filter(branch=branch, fecha__gte=date_from, fecha__lte=date_to)
            .order_by('fecha')
            .values(
                'fecha', 'ingreso_ventas_bob', 'costo_ventas_bob',
                'ganancia_bruta_bob', 'gastos_operativos_bob',
                'ganancia_neta_bob', 'margen_neto_pct',
                'num_ventas', 'num_compras',
            )
        )

    @staticmethod
    def resumen_periodo(branch, date_from: date, date_to: date) -> dict:
        """Resumen agregado de P&L para un período."""
        from .models import PnLDailySnapshot

        agg = (
            PnLDailySnapshot.objects
            .filter(branch=branch, fecha__gte=date_from, fecha__lte=date_to)
            .aggregate(
                total_ingreso=Sum('ingreso_ventas_bob'),
                total_costo=Sum('costo_ventas_bob'),
                total_bruta=Sum('ganancia_bruta_bob'),
                total_gastos=Sum('gastos_operativos_bob'),
                total_neta=Sum('ganancia_neta_bob'),
                total_ventas=Sum('num_ventas'),
                total_compras=Sum('num_compras'),
                dias=Count('id'),
            )
        )

        ingreso = _q(agg['total_ingreso'] or 0)
        neta    = _q(agg['total_neta'] or 0)
        margen  = (
            _q(neta / ingreso * 100, PCT_Q) if ingreso != 0 else _q(0, PCT_Q)
        )

        return {
            'periodo':               {'desde': str(date_from), 'hasta': str(date_to)},
            'dias_con_actividad':    agg['dias'] or 0,
            'total_ventas':          agg['total_ventas'] or 0,
            'total_compras':         agg['total_compras'] or 0,
            'ingreso_ventas_bob':    str(ingreso),
            'costo_ventas_bob':      str(_q(agg['total_costo'] or 0)),
            'ganancia_bruta_bob':    str(_q(agg['total_bruta'] or 0)),
            'gastos_operativos_bob': str(_q(agg['total_gastos'] or 0)),
            'ganancia_neta_bob':     str(neta),
            'margen_neto_pct':       str(margen),
        }


# ─────────────────────────────────────────────────────────────────────────────
# ExposureService — Riesgo de mercado por divisa
# ─────────────────────────────────────────────────────────────────────────────

# Umbral: si una divisa representa > X% del capital total → ALERT
EXPOSURE_WARNING_THRESHOLD  = Decimal('40')   # %
EXPOSURE_CRITICAL_THRESHOLD = Decimal('60')   # %


class ExposureService:

    @staticmethod
    def calcular_exposicion(branch=None) -> dict:
        """
        Calcula la exposición actual al riesgo de mercado.
        Devuelve estructura completa con exposición por divisa, totales y alertas.
        """
        from inventory.models import CurrencyInventory
        from rates.models import ExchangeRate, Currency

        bob = Currency.objects.filter(code='BOB').first()
        if not bob:
            return {'error': 'BOB no encontrado'}

        # Cargar tasas activas (paralelo físico empresa como benchmark de exposición)
        rates = {}
        for r in (ExchangeRate.objects
                  .filter(currency_to=bob, valid_until__isnull=True)
                  .filter(
                      Q(market_type='paralelo_fisico_empresa') |
                      Q(market_type='parallel')
                  )
                  .select_related('currency_from')
                  .order_by('currency_from__code', 'market_type')):
            # Priorizar paralelo_fisico_empresa sobre parallel
            if r.currency_from_id not in rates or r.market_type == 'paralelo_fisico_empresa':
                rates[r.currency_from_id] = r

        inv_qs = CurrencyInventory.objects.select_related('currency', 'branch')
        if branch:
            inv_qs = inv_qs.filter(branch=branch)

        divisas = []
        total_exposure = _q(0)

        for inv in inv_qs:
            if inv.currency.code == 'BOB' or inv.total_balance == 0:
                continue
            rate = rates.get(inv.currency_id)
            if not rate:
                continue

            scale          = Decimal(str(inv.currency.scale_factor or 1))
            sell_unit      = _q(rate.sell_rate / scale, RATE_Q)
            exposure       = _q(inv.total_balance * sell_unit)
            wac            = _q(inv.weighted_average_cost, RATE_Q)
            wac_unit       = _q(wac / scale, RATE_Q)
            unrealized_pnl = _q(inv.total_balance * (sell_unit - wac_unit))

            divisas.append({
                'currency_code':      inv.currency.code,
                'currency_name':      inv.currency.name,
                'scale_factor':       int(scale),
                'stock_units':        str(_q(inv.total_balance, RATE_Q)),
                'wac':                str(wac),
                'wac_unit':           str(wac_unit),
                'sell_rate_unit':     str(sell_unit),
                'sell_rate_lote':     str(rate.sell_rate),
                'exposure_bob':       str(exposure),
                'unrealized_pnl_bob': str(unrealized_pnl),
                'pct_of_capital':     None,  # se completa abajo
                'alert_level':        None,
                'branch':             inv.branch.name,
            })
            total_exposure += exposure

        # Calcular % del capital y nivel de alerta
        alertas = []
        for d in divisas:
            if total_exposure > 0:
                pct = _q(Decimal(d['exposure_bob']) / total_exposure * 100, PCT_Q)
            else:
                pct = _q(0, PCT_Q)
            d['pct_of_capital'] = str(pct)

            if pct >= EXPOSURE_CRITICAL_THRESHOLD:
                d['alert_level'] = 'CRITICAL'
                alertas.append(
                    f"CRÍTICO: {d['currency_code']} representa {pct}% de la "
                    f"exposición total ({d['exposure_bob']} BOB)"
                )
            elif pct >= EXPOSURE_WARNING_THRESHOLD:
                d['alert_level'] = 'WARNING'
                alertas.append(
                    f"ADVERTENCIA: {d['currency_code']} representa {pct}% "
                    f"de la exposición total"
                )
            else:
                d['alert_level'] = 'OK'

        divisas.sort(key=lambda x: -Decimal(x['exposure_bob']))

        return {
            'divisas':          divisas,
            'total_exposure_bob': str(total_exposure),
            'num_divisas':      len(divisas),
            'alertas':          alertas,
            'calculado_en':     timezone.now().isoformat(),
        }

    @staticmethod
    def guardar_snapshot(branch) -> list:
        """Guarda un ExposureSnapshot puntual para la sucursal."""
        from .models import ExposureSnapshot

        resultado = ExposureService.calcular_exposicion(branch=branch)
        snapshots = []
        now = timezone.now()

        for d in resultado.get('divisas', []):
            snap = ExposureSnapshot.objects.create(
                timestamp         = now,
                branch            = branch,
                currency_code     = d['currency_code'],
                currency_name     = d['currency_name'],
                scale_factor      = d['scale_factor'],
                stock_units       = Decimal(d['stock_units']),
                wac               = Decimal(d['wac']),
                sell_rate_unit    = Decimal(d['sell_rate_unit']),
                sell_rate_lote    = Decimal(d['sell_rate_lote']),
                exposure_bob      = Decimal(d['exposure_bob']),
                pct_of_capital    = Decimal(d['pct_of_capital']),
                unrealized_pnl_bob= Decimal(d['unrealized_pnl_bob']),
                alert_level       = d['alert_level'],
            )
            snapshots.append(snap)

        return snapshots

    @staticmethod
    def series_exposure(currency_code: str, branch, days: int = 30) -> list:
        """Serie temporal de exposición para gráficos."""
        from .models import ExposureSnapshot
        from_dt = timezone.now() - timedelta(days=days)

        return list(
            ExposureSnapshot.objects
            .filter(
                currency_code=currency_code,
                branch=branch,
                timestamp__gte=from_dt,
            )
            .order_by('timestamp')
            .values('timestamp', 'exposure_bob', 'pct_of_capital',
                    'sell_rate_unit', 'unrealized_pnl_bob', 'alert_level')
        )


# ─────────────────────────────────────────────────────────────────────────────
# SpreadService — Análisis y tracking de spreads
# ─────────────────────────────────────────────────────────────────────────────

# Spread mínimo considerado rentable (0.3%)
SPREAD_MINIMO_PCT = Decimal('0.30')


class SpreadService:

    @staticmethod
    def calcular_spreads(branch=None) -> list:
        """
        Calcula los spreads actuales de todas las tasas activas.
        Incluye comparación con el promedio histórico de 30 días.
        """
        from rates.models import ExchangeRate, Currency
        from .models import SpreadSnapshot

        bob = Currency.objects.filter(code='BOB').first()
        if not bob:
            return []

        tasas = (
            ExchangeRate.objects
            .filter(currency_to=bob, valid_until__isnull=True)
            .exclude(currency_from=bob)
            .select_related('currency_from')
            .order_by('currency_from__code', 'market_type')
        )

        resultado = []
        hace_30d  = timezone.now() - timedelta(days=30)

        for tasa in tasas:
            if tasa.buy_rate == 0:
                continue

            spread      = _q(tasa.sell_rate - tasa.buy_rate, RATE_Q)
            spread_pct  = _q(spread / tasa.buy_rate * 100, PCT_Q)
            prima_pct   = (
                _q((tasa.sell_rate / tasa.official_rate - 1) * 100, PCT_Q)
                if tasa.official_rate and tasa.official_rate != 0
                else _q(0, PCT_Q)
            )

            # Promedio histórico de los últimos 30 días
            hist = (
                SpreadSnapshot.objects
                .filter(
                    currency_code=tasa.currency_from.code,
                    market_type=tasa.market_type,
                    timestamp__gte=hace_30d,
                )
                .aggregate(
                    avg_spread=Avg('spread_bob'),
                    avg_pct=Avg('spread_pct'),
                )
            )

            resultado.append({
                'currency_code':     tasa.currency_from.code,
                'currency_name':     tasa.currency_from.name,
                'market_type':       tasa.market_type,
                'buy_rate':          str(tasa.buy_rate),
                'sell_rate':         str(tasa.sell_rate),
                'official_rate':     str(tasa.official_rate or 0),
                'spread_bob':        str(spread),
                'spread_pct':        str(spread_pct),
                'prima_oficial_pct': str(prima_pct),
                'spread_prom_30d':   str(_q(hist['avg_spread'] or 0, RATE_Q)),
                'spread_pct_prom_30d': str(_q(hist['avg_pct'] or 0, PCT_Q)),
                'alerta_spread_bajo': spread_pct < SPREAD_MINIMO_PCT,
            })

        resultado.sort(key=lambda x: x['currency_code'])
        return resultado

    @staticmethod
    def guardar_snapshot(branch=None) -> None:
        """Persiste un SpreadSnapshot para todas las tasas activas actuales."""
        from rates.models import ExchangeRate, Currency
        from .models import SpreadSnapshot

        bob = Currency.objects.filter(code='BOB').first()
        if not bob:
            return

        tasas = (
            ExchangeRate.objects
            .filter(currency_to=bob, valid_until__isnull=True)
            .exclude(currency_from=bob)
            .select_related('currency_from')
        )
        now = timezone.now()
        snapshots = []

        for tasa in tasas:
            if tasa.buy_rate == 0:
                continue
            spread     = _q(tasa.sell_rate - tasa.buy_rate, RATE_Q)
            spread_pct = _q(spread / tasa.buy_rate * 100, PCT_Q)
            prima_pct  = (
                _q((tasa.sell_rate / tasa.official_rate - 1) * 100, PCT_Q)
                if tasa.official_rate and tasa.official_rate != 0
                else _q(0, PCT_Q)
            )
            snapshots.append(SpreadSnapshot(
                timestamp         = now,
                currency_code     = tasa.currency_from.code,
                market_type       = tasa.market_type,
                buy_rate          = tasa.buy_rate,
                sell_rate         = tasa.sell_rate,
                official_rate     = tasa.official_rate,
                spread_bob        = spread,
                spread_pct        = spread_pct,
                prima_oficial_pct = prima_pct,
            ))

        if snapshots:
            SpreadSnapshot.objects.bulk_create(snapshots)

    @staticmethod
    def series_spread(currency_code: str, market_type: str = 'paralelo_fisico_empresa',
                      days: int = 30) -> list:
        """Serie temporal de spreads para un par divisa/mercado."""
        from .models import SpreadSnapshot
        from_dt = timezone.now() - timedelta(days=days)

        return list(
            SpreadSnapshot.objects
            .filter(
                currency_code=currency_code,
                market_type=market_type,
                timestamp__gte=from_dt,
            )
            .order_by('timestamp')
            .values('timestamp', 'buy_rate', 'sell_rate', 'spread_bob',
                    'spread_pct', 'prima_oficial_pct')
        )


# ─────────────────────────────────────────────────────────────────────────────
# DecisionEngine — Motor de decisión inteligente compra/venta de divisas
# ─────────────────────────────────────────────────────────────────────────────

class DecisionEngine:
    """
    Motor de decisiones híbrido (heurístico + scoring ponderado).

    SCORE PONDERADO (0–100):
      score = tendencia*0.3 + spread*0.2 + competencia*0.2 + binance*0.2 + liquidez*0.1

    DECISIÓN:
      > 65 → COMPRAR   (señales alcistas, buena liquidez, margen favorable)
      < 35 → VENDER    (señales bajistas, sobreexposición, spread bajo)
      35–65 → ESPERAR  (señales mixtas o datos insuficientes)

    RIESGO:
      BAJO   — volatilidad < 1%, datos frescos, sin alertas críticas
      MEDIO  — volatilidad 1–3% o alertas moderadas
      ALTO   — volatilidad > 3%, datos obsoletos, o alertas críticas
    """

    W_TENDENCIA   = Decimal('0.3')
    W_SPREAD      = Decimal('0.2')
    W_COMPETENCIA = Decimal('0.2')
    W_BINANCE     = Decimal('0.2')
    W_LIQUIDEZ    = Decimal('0.1')

    UMBRAL_COMPRAR = 65
    UMBRAL_VENDER  = 35

    # ── API principal ─────────────────────────────────────────────────────────

    @classmethod
    def evaluar(cls, currency: str, branch=None) -> dict:
        """
        Evalúa una divisa y devuelve recomendación completa con scores detallados.

        Args:
            currency: Código de divisa (e.g., 'USD', 'EUR', 'ARS')
            branch:   Sucursal (Branch instance) — requerido para contexto inventario/exposición

        Returns:
            dict con decision, confianza, precios recomendados, motivo, riesgo,
            score_total, scores_detalle, señales, alertas, heuristicas_aplicadas,
            datos, calculado_en
        """
        señales:     list = []
        alertas:     list = []
        heuristicas: list = []

        data = cls._gather(currency, branch)

        if not data['tiene_tasa']:
            return cls._sin_datos(currency, 'Sin tasa activa registrada para esta divisa')

        # ── Sub-scores ────────────────────────────────────────────────────────
        s_t, sig_t, alt_t = cls._score_tendencia(data)
        s_s, sig_s, alt_s = cls._score_spread(data)
        s_c, sig_c, alt_c = cls._score_competencia(data)
        s_b, sig_b, alt_b = cls._score_binance(data)
        s_l, sig_l, alt_l = cls._score_liquidez(data)

        for sigs, alts in [(sig_t, alt_t), (sig_s, alt_s), (sig_c, alt_c),
                           (sig_b, alt_b), (sig_l, alt_l)]:
            señales.extend(sigs)
            alertas.extend(alts)

        # ── Score total ponderado ─────────────────────────────────────────────
        score_total = float(
            Decimal(str(s_t)) * cls.W_TENDENCIA
            + Decimal(str(s_s)) * cls.W_SPREAD
            + Decimal(str(s_c)) * cls.W_COMPETENCIA
            + Decimal(str(s_b)) * cls.W_BINANCE
            + Decimal(str(s_l)) * cls.W_LIQUIDEZ
        )

        # ── Heurísticas de negocio (pueden forzar decisión) ───────────────────
        force_decision, heuristicas, alertas = cls._apply_heuristics(
            data, score_total, None, heuristicas, alertas
        )

        # ── Decisión final ────────────────────────────────────────────────────
        if force_decision:
            decision = force_decision
        elif score_total > cls.UMBRAL_COMPRAR:
            decision = 'COMPRAR'
        elif score_total < cls.UMBRAL_VENDER:
            decision = 'VENDER'
        else:
            decision = 'ESPERAR'

        precio_compra, precio_venta = cls._recommend_prices(data, decision)
        riesgo, confianza           = cls._risk_and_confidence(data, alertas)
        motivo = cls._build_motivo(decision, score_total, s_t, s_s, s_c, s_b, s_l)

        return {
            'currency':                  currency,
            'decision':                  decision,
            'confianza':                 confianza,
            'precio_recomendado_compra': str(precio_compra),
            'precio_recomendado_venta':  str(precio_venta),
            'motivo':                    motivo,
            'riesgo':                    riesgo,
            'score_total':               round(score_total, 2),
            'scores_detalle': {
                'tendencia':   round(s_t, 2),
                'spread':      round(s_s, 2),
                'competencia': round(s_c, 2),
                'binance':     round(s_b, 2),
                'liquidez':    round(s_l, 2),
            },
            'señales':               señales,
            'alertas':               alertas,
            'heuristicas_aplicadas': heuristicas,
            'datos': {
                'tasa_compra':       str(data.get('buy_rate', 0)),
                'tasa_venta':        str(data.get('sell_rate', 0)),
                'spread_pct':        str(data.get('spread_pct', 0)),
                'spread_avg_30d':    str(data.get('spread_avg_30d', 0)),
                'tendencia_24h_pct': str(data.get('tendencia_24h_pct', 0)),
                'tendencia_7d_pct':  str(data.get('tendencia_7d_pct', 0)),
                'volatilidad_pct':   str(data.get('volatilidad_pct', 0)),
                'stock_actual':      str(data.get('stock', 0)),
                'wac':               str(data.get('wac', 0)),
                'tasa_digital':      str(data.get('tasa_digital', 0)),
                'tasa_bcb':          str(data.get('tasa_bcb', 0)),
                'tasa_competencia':  str(data.get('tasa_competencia', 0)),
                'volumen_tx_24h':    data.get('volumen_tx_24h', 0),
            },
            'calculado_en': timezone.now().isoformat(),
        }

    @classmethod
    def recomendar(cls, currency_code: str, branch) -> dict:
        """
        Backward-compatible wrapper para analytics/views.py.
        Llama a evaluar() y devuelve el formato legacy más los campos nuevos.
        """
        result = cls.evaluar(currency_code, branch)

        if result.get('decision') == 'SIN_DATOS':
            return {
                'accion':  'SIN_DATOS',
                'score':   50,
                'señales': result.get('señales', ['Sin datos disponibles']),
                'alertas': [],
            }

        decision = result['decision']
        color_map = {'COMPRAR': 'success', 'VENDER': 'error', 'ESPERAR': 'warning'}

        return {
            # ── Campos legacy ─────────────────────────────────────────────────
            'currency_code': currency_code,
            'accion':        decision,
            'accion_color':  color_map.get(decision, 'warning'),
            'score':         result['score_total'],
            'razon':         result['motivo'],
            'señales':       result['señales'],
            'alertas':       result['alertas'],
            'stock_actual':  result['datos']['stock_actual'],
            'wac':           result['datos']['wac'],
            'calculado_en':  result['calculado_en'],
            # ── Campos nuevos ─────────────────────────────────────────────────
            'decision':                  decision,
            'confianza':                 result['confianza'],
            'riesgo':                    result['riesgo'],
            'precio_recomendado_compra': result['precio_recomendado_compra'],
            'precio_recomendado_venta':  result['precio_recomendado_venta'],
            'scores_detalle':            result['scores_detalle'],
            'heuristicas_aplicadas':     result['heuristicas_aplicadas'],
        }

    # ── Recopilación de datos ─────────────────────────────────────────────────

    @classmethod
    def _gather(cls, currency: str, branch) -> dict:
        """
        Recopila todas las señales necesarias para el scoring.
        Nunca lanza excepciones — retorna datos parciales si algo falla.
        """
        from rates.models import ExchangeRate
        from .models import SpreadSnapshot

        data: dict = {
            'currency':            currency,
            'branch':              branch,
            'tiene_tasa':          False,
            'tiene_inventario':    False,
            'buy_rate':            Decimal('0'),
            'sell_rate':           Decimal('0'),
            'spread_pct':          Decimal('0'),
            'spread_avg_30d':      Decimal('0'),
            'spread_min_30d':      Decimal('0'),
            'volatilidad_pct':     Decimal('0'),
            'tendencia_24h_pct':   Decimal('0'),
            'tendencia_7d_pct':    Decimal('0'),
            'tasa_digital':        Decimal('0'),
            'tasa_bcb':            Decimal('0'),
            'tasa_competencia':    Decimal('0'),
            'tasa_parallel':       Decimal('0'),
            'stock':               Decimal('0'),
            'wac':                 Decimal('0'),
            'reorder_point':       Decimal('0'),
            'maximum_stock':       Decimal('0'),
            'necesita_reposicion': False,
            'sobrestock':          False,
            'scale_factor':        Decimal('1'),
            'volumen_tx_24h':      0,
            'exposure_pct':        Decimal('0'),
            'exposure_level':      'OK',
            'prediccion_tendencia':  Decimal('0'),
            'prediccion_disponible': False,
            'datos_frescos':       True,
            'market_type_activo':  'paralelo_fisico_empresa',
        }

        # ── Tasa activa ───────────────────────────────────────────────────────
        try:
            tasas_qs = (
                ExchangeRate.objects
                .filter(currency_from__code=currency, valid_until__isnull=True)
                .select_related('currency_from', 'currency_to')
            )
            tasas = {t.market_type: t for t in tasas_qs}

            tasa = (
                tasas.get('paralelo_fisico_empresa')
                or tasas.get('parallel')
                or tasas.get('digital')
                or tasas.get('bcb')
                or tasas.get('official')
            )

            if tasa:
                scale = Decimal(str(tasa.currency_from.scale_factor or 1))
                data['scale_factor'] = scale
                data['buy_rate']     = _q(tasa.buy_rate  / scale, RATE_Q)
                data['sell_rate']    = _q(tasa.sell_rate / scale, RATE_Q)
                data['spread_pct']   = (
                    _q((tasa.sell_rate - tasa.buy_rate) / tasa.buy_rate * 100, PCT_Q)
                    if tasa.buy_rate > 0 else Decimal('0')
                )
                data['market_type_activo'] = tasa.market_type
                data['tiene_tasa'] = True

                if hasattr(tasa, 'updated_at') and tasa.updated_at:
                    age_h = (timezone.now() - tasa.updated_at).total_seconds() / 3600
                    data['datos_frescos'] = age_h < STALE_RATE_HOURS

                if 'digital' in tasas:
                    data['tasa_digital'] = _q(tasas['digital'].sell_rate / scale, RATE_Q)
                if 'bcb' in tasas:
                    data['tasa_bcb'] = _q(tasas['bcb'].sell_rate / scale, RATE_Q)
                if 'parallel' in tasas:
                    data['tasa_parallel'] = _q(tasas['parallel'].sell_rate / scale, RATE_Q)

                comp = (
                    tasas.get('parallel')
                    if tasa.market_type != 'parallel'
                    else tasas.get('paralelo_fisico_empresa')
                )
                if comp:
                    data['tasa_competencia'] = _q(comp.sell_rate / scale, RATE_Q)

        except Exception as exc:
            log.debug('DECISION_GATHER tasa err=%s', exc)

        # ── Spreads e historial de precios ────────────────────────────────────
        try:
            now  = timezone.now()
            mt   = data['market_type_activo']
            snaps = list(
                SpreadSnapshot.objects
                .filter(
                    currency_code=currency,
                    market_type=mt,
                    timestamp__gte=now - timedelta(days=30),
                )
                .order_by('timestamp')
                .values_list('sell_rate', 'spread_pct', 'timestamp')
            )

            if snaps:
                spreads   = [Decimal(str(r[1])) for r in snaps]
                avg_sp    = sum(spreads) / len(spreads)
                data['spread_avg_30d'] = _q(avg_sp, PCT_Q)
                data['spread_min_30d'] = _q(min(spreads), PCT_Q)

                sell_rates = [Decimal(str(r[0])) for r in snaps]
                if len(sell_rates) > 1:
                    mean_sr  = sum(sell_rates) / len(sell_rates)
                    variance = sum((r - mean_sr) ** 2 for r in sell_rates) / len(sell_rates)
                    std_dev  = variance.sqrt()
                    data['volatilidad_pct'] = (
                        _q(std_dev / mean_sr * 100, PCT_Q) if mean_sr > 0 else Decimal('0')
                    )

                # Tendencia 24h
                snaps_24h = [(r[0], r[2]) for r in snaps if r[2] >= now - timedelta(hours=24)]
                if len(snaps_24h) >= 2:
                    r0 = Decimal(str(snaps_24h[0][0]))
                    r1 = Decimal(str(snaps_24h[-1][0]))
                    if r0 > 0:
                        data['tendencia_24h_pct'] = _q((r1 - r0) / r0 * 100, PCT_Q)

                # Tendencia 7d
                snaps_7d = [(r[0], r[2]) for r in snaps if r[2] >= now - timedelta(days=7)]
                if len(snaps_7d) >= 2:
                    r0 = Decimal(str(snaps_7d[0][0]))
                    r1 = Decimal(str(snaps_7d[-1][0]))
                    if r0 > 0:
                        data['tendencia_7d_pct'] = _q((r1 - r0) / r0 * 100, PCT_Q)

        except Exception as exc:
            log.debug('DECISION_GATHER spreads err=%s', exc)

        # ── Inventario ────────────────────────────────────────────────────────
        if branch:
            try:
                from inventory.models import CurrencyInventory
                inv = CurrencyInventory.objects.get(currency__code=currency, branch=branch)
                data['stock']               = _q(inv.total_balance, RATE_Q)
                data['wac']                 = _q(inv.weighted_average_cost, RATE_Q)
                data['reorder_point']       = _q(inv.reorder_point, RATE_Q)
                data['maximum_stock']       = _q(inv.maximum_stock, RATE_Q)
                data['necesita_reposicion'] = inv.needs_replenishment
                data['sobrestock']          = inv.is_overstocked
                data['tiene_inventario']    = True
            except Exception as exc:
                log.debug('DECISION_GATHER inv err=%s', exc)

        # ── Volumen de transacciones (últimas 24h) ────────────────────────────
        try:
            from transactions.models import Transaction
            q_filter = Q(currency_from__code=currency) | Q(currency_to__code=currency)
            if branch:
                q_filter &= Q(branch=branch)
            data['volumen_tx_24h'] = Transaction.objects.filter(
                q_filter,
                status='COMPLETED',
                created_at__gte=timezone.now() - timedelta(hours=24),
            ).count()
        except Exception as exc:
            log.debug('DECISION_GATHER txvol err=%s', exc)

        # ── Exposición de riesgo ──────────────────────────────────────────────
        if branch:
            try:
                exp = ExposureService.calcular_exposicion(branch=branch)
                for d in exp.get('divisas', []):
                    if d['currency_code'] == currency:
                        data['exposure_pct']   = _q(d.get('pct_of_capital', 0), PCT_Q)
                        data['exposure_level'] = d.get('alert_level', 'OK')
                        break
            except Exception as exc:
                log.debug('DECISION_GATHER exp err=%s', exc)

        # ── Predicción ML (opcional) ──────────────────────────────────────────
        try:
            from predictions.models import Prediction
            preds = (
                Prediction.objects
                .filter(
                    currency_pair=f'{currency}/BOB',
                    prediction_date__gte=timezone.now(),
                    prediction_date__lte=timezone.now() + timedelta(days=7),
                )
                .order_by('prediction_date')
            )
            if preds.count() >= 2:
                r0 = Decimal(str(preds.first().predicted_sell_rate))
                r1 = Decimal(str(preds.last().predicted_sell_rate))
                if r0 > 0:
                    data['prediccion_tendencia']  = _q((r1 - r0) / r0 * 100, PCT_Q)
                    data['prediccion_disponible'] = True
        except Exception as exc:
            log.debug('DECISION_GATHER pred err=%s', exc)

        return data

    # ── Sub-scores (cada uno devuelve float 0–100, señales, alertas) ──────────

    @classmethod
    def _score_tendencia(cls, data: dict) -> tuple:
        """Score tendencia 24h + 7d + predicción ML. Fórmula: 50 + clamp(combined*10, -50,50)."""
        señales, alertas = [], []
        t24h = float(data['tendencia_24h_pct'])
        t7d  = float(data['tendencia_7d_pct'])
        pred = float(data['prediccion_tendencia']) if data['prediccion_disponible'] else 0.0

        combined = t24h * 0.5 + t7d * 0.3 + pred * 0.2
        score    = 50.0 + max(-50.0, min(50.0, combined * 10))

        if t24h > 0.1:
            señales.append(f'Tendencia alcista 24h: +{t24h:.2f}%')
        elif t24h < -0.1:
            alertas.append(f'Tendencia bajista 24h: {t24h:.2f}%')

        if t7d > 0.5:
            señales.append(f'Tendencia semanal positiva: +{t7d:.2f}% en 7 días')
        elif t7d < -0.5:
            alertas.append(f'Tendencia semanal negativa: {t7d:.2f}% en 7 días')

        if data['prediccion_disponible'] and abs(pred) > 0.3:
            dir_pred = 'alcista' if pred > 0 else 'bajista'
            señales.append(f'Predicción IA: tendencia {dir_pred} {pred:+.2f}% (7 días)')

        return score, señales, alertas

    @classmethod
    def _score_spread(cls, data: dict) -> tuple:
        """Score spread actual vs promedio 30d y umbral mínimo rentable."""
        señales, alertas = [], []
        sp_actual = float(data['spread_pct'])
        sp_avg30  = float(data['spread_avg_30d'])
        sp_min    = float(SPREAD_MINIMO_PCT)

        if sp_actual < sp_min:
            alertas.append(f'Spread por debajo del mínimo operativo: {sp_actual:.4f}% < {sp_min:.2f}%')
            return 10.0, señales, alertas

        if sp_avg30 > 0:
            delta_rel = (sp_actual - sp_avg30) / sp_avg30
            score     = 50.0 + max(-45.0, min(45.0, delta_rel * 100))
            if delta_rel > 0.1:
                señales.append(
                    f'Spread {sp_actual:.4f}% > promedio 30d ({sp_avg30:.4f}%): rentabilidad alta'
                )
            elif delta_rel < -0.2:
                alertas.append(
                    f'Spread {sp_actual:.4f}% < promedio 30d ({sp_avg30:.4f}%): margen deteriorado'
                )
        else:
            score = 55.0
            señales.append(f'Spread actual: {sp_actual:.4f}% (sin histórico disponible)')

        return score, señales, alertas

    @classmethod
    def _score_competencia(cls, data: dict) -> tuple:
        """Score comparando nuestra tasa vs referencia del mercado paralelo."""
        señales, alertas = [], []
        nuestra = float(data['sell_rate'])
        comp    = float(data['tasa_competencia']) or float(data['tasa_parallel'])

        if not comp or nuestra == 0:
            return 50.0, señales, alertas

        diff_pct = (nuestra - comp) / comp * 100

        if diff_pct < -2:
            score = min(100.0, 75.0 + abs(diff_pct) * 5)
            señales.append(
                f'Precio competitivo: venta {nuestra:.4f} ≤ paralelo {comp:.4f} '
                f'(ventaja {abs(diff_pct):.2f}%)'
            )
        elif diff_pct > 3:
            score = max(10.0, 50.0 - diff_pct * 5)
            alertas.append(
                f'Precio {diff_pct:.2f}% por encima del paralelo — riesgo de perder clientes'
            )
        else:
            score = 50.0
            señales.append(f'Precio en línea con el mercado paralelo ({diff_pct:+.2f}%)')

        return score, señales, alertas

    @classmethod
    def _score_binance(cls, data: dict) -> tuple:
        """Score comparando tasa física vs referencia digital (Binance/exchange digital)."""
        señales, alertas = [], []
        nuestra = float(data['sell_rate'])
        digital = float(data['tasa_digital'])

        if not digital or nuestra == 0:
            return 50.0, señales, alertas

        prima_pct = (nuestra - digital) / digital * 100

        if prima_pct < 0:
            score = max(20.0, 50.0 + prima_pct * 10)
            alertas.append(
                f'Tasa física ({nuestra:.4f}) por debajo del digital ({digital:.4f}): '
                f'{prima_pct:.2f}% — inusual, revisar'
            )
        elif prima_pct <= 3:
            score = 50.0 + prima_pct * 5
            señales.append(f'Prima físico/digital saludable: {prima_pct:.2f}%')
        else:
            score = max(20.0, 80.0 - (prima_pct - 3) * 8)
            alertas.append(
                f'Prima físico/digital elevada: {prima_pct:.2f}% — '
                f'posible migración de clientes al canal digital'
            )

        return score, señales, alertas

    @classmethod
    def _score_liquidez(cls, data: dict) -> tuple:
        """Score de inventario físico: stock bajo → COMPRAR, sobrestock → VENDER."""
        señales, alertas = [], []
        stock   = float(data['stock'])
        reorder = float(data['reorder_point'])
        maximum = float(data['maximum_stock'])
        volumen = data['volumen_tx_24h']

        if maximum <= 0:
            if volumen > 10:
                señales.append(f'Volumen alto: {volumen} transacciones en 24h')
                return 60.0, señales, alertas
            return 50.0, señales, alertas

        if data['necesita_reposicion']:
            score = 85.0 if stock < reorder * 0.5 else 70.0
            señales.append(f'Stock bajo ({stock:.2f}): reponer antes del punto crítico ({reorder:.2f})')
        elif data['sobrestock']:
            score = 20.0
            alertas.append(f'Sobrestock ({stock:.2f} > máximo {maximum:.2f}): liberar capital')
        else:
            rango   = maximum - reorder
            pos_rel = (stock - reorder) / rango if rango > 0 else 0.5
            score   = 60.0 - pos_rel * 40      # 60 @ reorder → 20 @ maximum
            señales.append(
                f'Stock en rango normal ({stock:.2f}): '
                f'{pos_rel * 100:.0f}% del rango [reorder → máximo]'
            )

        if volumen > 15:
            score = min(100.0, score + 10)
            señales.append(f'Volumen elevado ({volumen} tx/24h): liquidez crítica')
        elif volumen > 5:
            score = min(100.0, score + 5)

        return score, señales, alertas

    # ── Heurísticas de negocio ─────────────────────────────────────────────────

    @classmethod
    def _apply_heuristics(cls, data: dict, score: float,
                          force: 'str | None', heuristicas: list,
                          alertas: list) -> tuple:
        """Reglas de negocio que pueden forzar la decisión final."""
        sp_pct = float(data['spread_pct'])
        sp_min = float(SPREAD_MINIMO_PCT)

        if sp_pct <= 0:
            force = 'ESPERAR'
            heuristicas.append('H1: Spread negativo o cero — tasas requieren corrección')
            alertas.append(f'CRÍTICO: spread = {sp_pct:.4f}% — revisar tasas')

        elif sp_pct < sp_min and not force:
            force = 'ESPERAR'
            heuristicas.append(
                f'H2: Spread {sp_pct:.4f}% < mínimo {sp_min:.2f}% — sin margen para operar'
            )

        if data['exposure_level'] == 'CRITICAL' and not force:
            force = 'VENDER'
            pct = float(data['exposure_pct'])
            heuristicas.append(
                f'H3: Concentración CRÍTICA ({pct:.1f}% en {data["currency"]}) — reducir obligatorio'
            )
            alertas.append(
                f'Concentración {pct:.1f}% supera límite {float(EXPOSURE_CRITICAL_PCT):.0f}%'
            )

        if float(data['stock']) == 0 and force == 'VENDER':
            force = 'ESPERAR'
            heuristicas.append('H4: Sin stock físico — imposible ejecutar venta')

        if not data['datos_frescos']:
            heuristicas.append('H5: Tasa desactualizada (> 2h) — confianza reducida')
            alertas.append('Tasa con más de 2h sin actualizar: precios recomendados pueden no ser exactos')

        return force, heuristicas, alertas

    # ── Precios recomendados ───────────────────────────────────────────────────

    @classmethod
    def _recommend_prices(cls, data: dict, decision: str) -> tuple:
        """
        Precio venta: WAC * (1 + 1.5%) — garantiza rentabilidad sobre costo.
        Precio compra: referencia de mercado * 0.985 — margen de entrada.
        """
        wac       = data.get('wac',              Decimal('0'))
        buy_rate  = data.get('buy_rate',         Decimal('0'))
        sell_rate = data.get('sell_rate',        Decimal('0'))
        comp      = data.get('tasa_competencia', Decimal('0')) or sell_rate

        MARGEN_VENTA   = Decimal('0.015')   # 1.5%
        MARGEN_COMPRA  = Decimal('0.985')   # comprar 1.5% bajo referencia

        if wac > 0:
            precio_venta = _q(wac * (1 + MARGEN_VENTA), RATE_Q)
            precio_venta = max(precio_venta, sell_rate)
        else:
            precio_venta = sell_rate

        ref_compra    = min(comp, sell_rate) if comp > 0 else sell_rate
        precio_compra = _q(ref_compra * MARGEN_COMPRA, RATE_Q)
        if buy_rate > 0:
            precio_compra = min(precio_compra, buy_rate)

        return _q(precio_compra, RATE_Q), _q(precio_venta, RATE_Q)

    # ── Riesgo y confianza ────────────────────────────────────────────────────

    @classmethod
    def _risk_and_confidence(cls, data: dict, alertas: list) -> tuple:
        """Clasifica riesgo (BAJO/MEDIO/ALTO) y calcula confianza (0–100)."""
        volatilidad = float(data.get('volatilidad_pct', 0))
        fresco      = data.get('datos_frescos', True)
        tiene_hist  = float(data.get('spread_avg_30d', 0)) > 0
        tiene_pred  = data.get('prediccion_disponible', False)
        n_alertas   = len(alertas)

        if volatilidad > 3 or not fresco or data.get('exposure_level') == 'CRITICAL':
            riesgo = 'ALTO'
        elif volatilidad > 1 or n_alertas >= 2:
            riesgo = 'MEDIO'
        else:
            riesgo = 'BAJO'

        confianza = 80
        if not tiene_hist:
            confianza -= 20
        if not fresco:
            confianza -= 10
        if tiene_pred:
            confianza += 5
        if not data.get('tiene_inventario', False):
            confianza -= 15
        confianza -= min(30, n_alertas * 5)
        confianza  = max(5, min(100, confianza))

        return riesgo, confianza

    # ── Motivo principal ──────────────────────────────────────────────────────

    @staticmethod
    def _build_motivo(decision: str, score: float,
                      s_t: float, s_s: float, s_c: float,
                      s_b: float, s_l: float) -> str:
        """Texto explicativo conciso basado en el factor dominante del score."""
        weighted = [
            ('tendencia',   s_t * 0.3),
            ('spread',      s_s * 0.2),
            ('competencia', s_c * 0.2),
            ('binance',     s_b * 0.2),
            ('liquidez',    s_l * 0.1),
        ]
        factor = max(weighted, key=lambda x: x[1])[0]
        _MOTIVOS = {
            ('COMPRAR', 'tendencia'):   'Tendencia alcista — buen momento para incrementar posición',
            ('COMPRAR', 'spread'):      'Spread sobre promedio — operación con margen favorable',
            ('COMPRAR', 'competencia'): 'Precio competitivo — capturar demanda del mercado',
            ('COMPRAR', 'binance'):     'Prima físico/digital favorable — buen margen sobre digital',
            ('COMPRAR', 'liquidez'):    'Stock bajo — reponer antes de quedarse sin divisa',
            ('VENDER',  'tendencia'):   'Tendencia bajista — reducir exposición antes de pérdidas',
            ('VENDER',  'spread'):      'Spread deteriorado — margen operativo insuficiente',
            ('VENDER',  'competencia'): 'Precio alto vs competencia — riesgo de perder clientes',
            ('VENDER',  'binance'):     'Prima física elevada — migración al canal digital posible',
            ('VENDER',  'liquidez'):    'Sobrestock — liberar capital inmovilizado',
            ('ESPERAR', 'tendencia'):   'Señales de tendencia mixtas — aguardar confirmación',
            ('ESPERAR', 'spread'):      'Spread en zona neutral — sin ventaja clara para operar',
            ('ESPERAR', 'competencia'): 'Mercado equilibrado — mantener posición actual',
            ('ESPERAR', 'binance'):     'Paridad físico/digital estable — sin urgencia operativa',
            ('ESPERAR', 'liquidez'):    'Inventario en rango normal — sin acción requerida',
        }
        return _MOTIVOS.get(
            (decision, factor),
            f'{decision} (score={score:.1f}) — evaluar contexto de mercado'
        )

    # ── Sin datos ─────────────────────────────────────────────────────────────

    @staticmethod
    def _sin_datos(currency: str, motivo: str) -> dict:
        return {
            'currency':                  currency,
            'decision':                  'SIN_DATOS',
            'confianza':                 0,
            'precio_recomendado_compra': '0',
            'precio_recomendado_venta':  '0',
            'motivo':                    motivo,
            'riesgo':                    'ALTO',
            'score_total':               0,
            'scores_detalle':            {},
            'señales':                   [motivo],
            'alertas':                   [],
            'heuristicas_aplicadas':     [],
            'datos':                     {},
            'calculado_en':              timezone.now().isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
#  AnomalyDetector — motor de detección de anomalías financieras
# ─────────────────────────────────────────────────────────────────────────────

# ── Umbrales (configurables vía settings) ─────────────────────────────────────

def _cfg(key, default):
    from django.conf import settings
    return getattr(settings, key, default)


# Capital drop
CAPITAL_DROP_WARNING_PCT  = Decimal('3')    # %
CAPITAL_DROP_CRITICAL_PCT = Decimal('5')    # %
CAPITAL_DROP_WINDOW_HOURS = 1               # comparar contra snapshot < N horas

# Missing cash (reconciliación CashFlowLog vs CashBOB declarado)
MISSING_CASH_WARNING_BOB  = Decimal('50')
MISSING_CASH_CRITICAL_BOB = Decimal('500')

# P&L neto negativo (señal de pérdida operativa)
PNL_NEG_WARNING_BOB       = Decimal('200')

# Tasa estancada (sin actualizar durante horario hábil)
STALE_RATE_HOURS          = 2
BUSINESS_HOURS_START      = 8    # 08:00 Bolivia
BUSINESS_HOURS_END        = 20   # 20:00 Bolivia

# Desviación sobre tasa BCB oficial
RATE_BCB_DEV_WARNING_PCT  = Decimal('15')   # %
RATE_BCB_DEV_CRITICAL_PCT = Decimal('30')   # %

# Spread mínimo rentable (ya existe en SpreadService pero se centraliza aquí)
SPREAD_MIN_PCT            = Decimal('0.30')  # %

# Exposición de divisa (ya existe en ExposureService)
EXPOSURE_WARNING_PCT      = Decimal('40')
EXPOSURE_CRITICAL_PCT     = Decimal('60')


def _anomaly(rule: str, severity: str, description: str,
             value, threshold, currency: str = '',
             branch=None, details: dict = None) -> dict:
    """Construye un dict de anomalía estandarizado."""
    return {
        'rule':        rule,
        'severity':    severity,
        'description': description,
        'value':       str(_q(Decimal(str(value)))),
        'threshold':   str(_q(Decimal(str(threshold)))),
        'currency':    currency,
        'branch_id':   branch.id if branch else None,
        'branch_code': branch.code if branch else None,
        'details':     details or {},
    }


class AnomalyDetector:
    """
    Ejecuta todas las reglas de detección y retorna una lista de anomalías.

    Uso:
        anomalies = AnomalyDetector.run_all(branch=branch, persist=True)

    Cada elemento de la lista tiene forma:
        {
          rule, severity, description,
          value, threshold, currency,
          branch_id, branch_code, details
        }

    Las reglas son independientes; un fallo en una no aborta las demás.
    """

    # ── Punto de entrada ──────────────────────────────────────────────────────

    @classmethod
    def run_all(cls, branch=None, persist: bool = True) -> list:
        """
        Ejecuta todas las reglas de detección.
        Si persist=True, persiste en CapitalAnomalyLog (deduplicando por ventana).
        """
        anomalies: list = []

        runners = [
            ('CAPITAL_DROP',       lambda: cls._check_capital_drop(branch)),
            ('MISSING_CASH',       lambda: cls._check_missing_cash(branch)),
            ('NEGATIVE_BALANCE',   lambda: cls._check_negative_balances(branch)),
            ('RATE_INVERTED',      lambda: cls._check_rate_inverted()),
            ('RATE_STALE',         lambda: cls._check_rate_stale()),
            ('RATE_BCB_DEVIATION', lambda: cls._check_rate_bcb_deviation()),
            ('SPREAD_BELOW_MIN',   lambda: cls._check_spread_below_min()),
            ('EXPOSURE_HIGH',      lambda: cls._check_exposure(branch)),
        ]

        for rule_name, fn in runners:
            try:
                results = fn()
                anomalies.extend(results)
            except Exception as exc:
                log.error('ANOMALY_RULE_FAIL rule=%s err=%s', rule_name, exc, exc_info=True)

        if persist and anomalies:
            cls._persist(anomalies)

        summary = {s: sum(1 for a in anomalies if a['severity'] == s)
                   for s in ('CRITICAL', 'WARNING', 'INFO')}
        log.info(
            'ANOMALY_SCAN branch=%s total=%d CRITICAL=%d WARNING=%d INFO=%d',
            branch.code if branch else 'ALL',
            len(anomalies), summary['CRITICAL'], summary['WARNING'], summary['INFO'],
        )
        return anomalies

    # ── Regla 1: Caída de capital ─────────────────────────────────────────────

    @staticmethod
    def _check_capital_drop(branch=None) -> list:
        """
        Compara el capital neto actual contra el snapshot más reciente
        de la última hora.  Dispara WARNING ≥3 % y CRITICAL ≥5 %.
        """
        from capital.services import CapitalService
        from snapshots.models import SystemSnapshot

        anomalies = []
        try:
            current = CapitalService.calcular_capital(branch=branch)
            current_total = Decimal(current.get('capital_neto') or '0')
        except Exception as exc:
            log.warning('ANOMALY_CAPITAL_DROP_CALC_FAIL err=%s', exc)
            return anomalies

        if current_total <= 0:
            return anomalies

        window = timezone.now() - timedelta(hours=CAPITAL_DROP_WINDOW_HOURS)
        qs = SystemSnapshot.objects.filter(timestamp__gte=window)
        if branch:
            qs = qs.filter(branch=branch)
        prev = qs.order_by('timestamp').first()

        if not prev:
            return anomalies

        try:
            prev_total = Decimal(
                prev.data_json.get('capital', {}).get('total_bob') or '0'
            )
        except Exception:
            return anomalies

        if prev_total <= 0:
            return anomalies

        drop_pct = (prev_total - current_total) / prev_total * 100

        if drop_pct >= CAPITAL_DROP_CRITICAL_PCT:
            severity = 'CRITICAL'
        elif drop_pct >= CAPITAL_DROP_WARNING_PCT:
            severity = 'WARNING'
        else:
            return anomalies

        anomalies.append(_anomaly(
            rule        = 'CAPITAL_DROP',
            severity    = severity,
            description = (
                f'Capital cayó {_q(drop_pct, PCT_Q)}% en la última hora '
                f'(de Bs.{prev_total:.2f} a Bs.{current_total:.2f})'
            ),
            value     = drop_pct,
            threshold = (CAPITAL_DROP_CRITICAL_PCT
                         if severity == 'CRITICAL' else CAPITAL_DROP_WARNING_PCT),
            branch    = branch,
            details   = {
                'capital_anterior': str(prev_total),
                'capital_actual':   str(current_total),
                'drop_pct':         str(_q(drop_pct, PCT_Q)),
                'snapshot_id':      prev.id,
                'snapshot_ts':      prev.timestamp.isoformat(),
                'window_hours':     CAPITAL_DROP_WINDOW_HOURS,
            },
        ))
        return anomalies

    # ── Regla 2: Diferencia en caja (Missing cash) ────────────────────────────

    @staticmethod
    def _check_missing_cash(branch=None) -> list:
        """
        Reconcilia el efectivo declarado (CashBOB) contra los movimientos
        del CashFlowLog del día.

        esperado = efectivo_ayer + entradas_hoy - salidas_hoy
        discrepancia = |esperado - declarado|

        Si no hay CashBOB hoy → INFO (falta el reconteo diario).
        discrepancia ≥ Bs.50  → WARNING
        discrepancia ≥ Bs.500 → CRITICAL
        """
        from capital.models import CashBOB, CashFlowLog

        anomalies = []
        today     = timezone.localdate()
        yesterday = today - timedelta(days=1)

        qs_branch = CashBOB.objects.filter(branch=branch) if branch else CashBOB.objects.all()

        # Sin registro CashBOB hoy → INFO
        if not qs_branch.filter(fecha=today).exists():
            anomalies.append(_anomaly(
                rule        = 'MISSING_CASH',
                severity    = 'INFO',
                description = 'No se ha registrado el reconteo de caja BOB para hoy',
                value       = 0,
                threshold   = 0,
                branch      = branch,
                details     = {'fecha': str(today)},
            ))
            return anomalies

        cash_hoy = qs_branch.get(fecha=today)

        # Base: efectivo declarado ayer (si no hay, base = 0)
        try:
            cash_ayer = qs_branch.get(fecha=yesterday)
            base = cash_ayer.total_efectivo_fisico()
        except CashBOB.DoesNotExist:
            base = Decimal('0')

        # Movimientos del CashFlowLog de hoy
        log_qs = CashFlowLog.objects.filter(fecha=today)
        if branch:
            log_qs = log_qs.filter(branch=branch)
        entradas = log_qs.filter(tipo='IN').aggregate(
            total=Sum('monto_bob'))['total'] or Decimal('0')
        salidas  = log_qs.filter(tipo='OUT').aggregate(
            total=Sum('monto_bob'))['total'] or Decimal('0')

        esperado    = _q(base + entradas - salidas)
        declarado   = _q(cash_hoy.total_efectivo_fisico())
        discrepancia = abs(esperado - declarado)

        if discrepancia >= MISSING_CASH_CRITICAL_BOB:
            severity = 'CRITICAL'
        elif discrepancia >= MISSING_CASH_WARNING_BOB:
            severity = 'WARNING'
        else:
            return anomalies

        anomalies.append(_anomaly(
            rule        = 'MISSING_CASH',
            severity    = severity,
            description = (
                f'Discrepancia de caja: esperado Bs.{esperado:.2f}, '
                f'declarado Bs.{declarado:.2f} '
                f'(diferencia Bs.{discrepancia:.2f})'
            ),
            value     = discrepancia,
            threshold = (MISSING_CASH_CRITICAL_BOB
                         if severity == 'CRITICAL' else MISSING_CASH_WARNING_BOB),
            branch    = branch,
            details   = {
                'base_ayer':    str(base),
                'entradas_hoy': str(entradas),
                'salidas_hoy':  str(salidas),
                'esperado':     str(esperado),
                'declarado':    str(declarado),
                'discrepancia': str(discrepancia),
            },
        ))
        return anomalies

    # ── Regla 3: Saldos negativos ─────────────────────────────────────────────

    @staticmethod
    def _check_negative_balances(branch=None) -> list:
        """
        Escanea:
          · CurrencyInventory.total_balance < 0           → CRITICAL
          · CapitalComposicion.capital_neto_local < 0     → CRITICAL
          · PnLDailySnapshot.ganancia_neta_bob < -Bs.200  → WARNING
        """
        from inventory.models import CurrencyInventory
        from capital.models import CapitalComposicion
        from .models import PnLDailySnapshot

        anomalies = []
        today = timezone.localdate()

        # Inventario negativo
        inv_qs = CurrencyInventory.objects.select_related('currency', 'branch')
        if branch:
            inv_qs = inv_qs.filter(branch=branch)

        for inv in inv_qs:
            if inv.total_balance < 0:
                anomalies.append(_anomaly(
                    rule        = 'NEGATIVE_BALANCE',
                    severity    = 'CRITICAL',
                    description = (
                        f'Inventario negativo: {inv.currency.code} = '
                        f'{inv.total_balance:.4f} en {inv.branch.code}'
                    ),
                    value     = inv.total_balance,
                    threshold = 0,
                    currency  = inv.currency.code,
                    branch    = inv.branch,
                    details   = {
                        'physical_balance': str(inv.physical_balance),
                        'digital_balance':  str(inv.digital_balance),
                        'total_balance':    str(inv.total_balance),
                        'wac':              str(inv.weighted_average_cost),
                    },
                ))

        # Capital neto local negativo
        comp_qs = CapitalComposicion.objects.select_related('branch').filter(fecha=today)
        if branch:
            comp_qs = comp_qs.filter(branch=branch)

        for comp in comp_qs:
            if comp.capital_neto_local < 0:
                anomalies.append(_anomaly(
                    rule        = 'NEGATIVE_BALANCE',
                    severity    = 'CRITICAL',
                    description = (
                        f'Capital neto negativo en {comp.branch.code}: '
                        f'Bs.{comp.capital_neto_local:.2f}'
                    ),
                    value     = comp.capital_neto_local,
                    threshold = 0,
                    branch    = comp.branch,
                    details   = {
                        'total_efectivo': str(comp.total_efectivo),
                        'total_digital':  str(comp.total_digital),
                        'pasivos':        str(comp.pasivos),
                        'capital_neto':   str(comp.capital_neto_local),
                    },
                ))

        # P&L neto negativo
        pnl_qs = PnLDailySnapshot.objects.filter(fecha=today)
        if branch:
            pnl_qs = pnl_qs.filter(branch=branch)

        for pnl in pnl_qs:
            if pnl.ganancia_neta_bob < -PNL_NEG_WARNING_BOB:
                anomalies.append(_anomaly(
                    rule        = 'NEGATIVE_BALANCE',
                    severity    = 'WARNING',
                    description = (
                        f'Pérdida neta del día en {pnl.branch.code}: '
                        f'Bs.{pnl.ganancia_neta_bob:.2f}'
                    ),
                    value     = pnl.ganancia_neta_bob,
                    threshold = -PNL_NEG_WARNING_BOB,
                    branch    = pnl.branch,
                    details   = {
                        'ganancia_bruta':    str(pnl.ganancia_bruta_bob),
                        'gastos_operativos': str(pnl.gastos_operativos_bob),
                        'ganancia_neta':     str(pnl.ganancia_neta_bob),
                        'num_ventas':        pnl.num_ventas,
                    },
                ))

        return anomalies

    # ── Regla 4a: Spread invertido ────────────────────────────────────────────

    @staticmethod
    def _check_rate_inverted() -> list:
        """
        sell_rate < buy_rate → CRITICAL (spread negativo)
        sell_rate == buy_rate → WARNING (margen cero)
        buy_rate == 0 → CRITICAL (operación imposible)
        """
        from rates.models import ExchangeRate, Currency

        anomalies = []
        bob = Currency.objects.filter(code='BOB').first()
        if not bob:
            return anomalies

        tasas = (ExchangeRate.objects
                 .filter(currency_to=bob, valid_until__isnull=True)
                 .exclude(currency_from=bob)
                 .select_related('currency_from'))

        for t in tasas:
            code = t.currency_from.code

            if t.buy_rate == 0:
                anomalies.append(_anomaly(
                    rule        = 'RATE_INVERTED',
                    severity    = 'CRITICAL',
                    description = f'{code}: buy_rate = 0 — operación imposible',
                    value       = 0,
                    threshold   = 0,
                    currency    = code,
                    details     = {
                        'market_type': t.market_type,
                        'buy_rate':    str(t.buy_rate),
                        'sell_rate':   str(t.sell_rate),
                        'rate_id':     t.id,
                    },
                ))
            elif t.sell_rate < t.buy_rate:
                anomalies.append(_anomaly(
                    rule        = 'RATE_INVERTED',
                    severity    = 'CRITICAL',
                    description = (
                        f'{code} [{t.market_type}]: spread negativo '
                        f'(sell {t.sell_rate} < buy {t.buy_rate})'
                    ),
                    value     = t.sell_rate - t.buy_rate,
                    threshold = 0,
                    currency  = code,
                    details   = {
                        'market_type': t.market_type,
                        'buy_rate':    str(t.buy_rate),
                        'sell_rate':   str(t.sell_rate),
                        'rate_id':     t.id,
                    },
                ))
            elif t.sell_rate == t.buy_rate:
                anomalies.append(_anomaly(
                    rule        = 'RATE_INVERTED',
                    severity    = 'WARNING',
                    description = (
                        f'{code} [{t.market_type}]: spread cero '
                        f'(sell = buy = {t.sell_rate})'
                    ),
                    value     = 0,
                    threshold = 0,
                    currency  = code,
                    details   = {
                        'market_type': t.market_type,
                        'buy_rate':    str(t.buy_rate),
                        'sell_rate':   str(t.sell_rate),
                        'rate_id':     t.id,
                    },
                ))

        return anomalies

    # ── Regla 4b: Tasa desactualizada ─────────────────────────────────────────

    @staticmethod
    def _check_rate_stale() -> list:
        """
        Si estamos en horario hábil (08:00–20:00 Bolivia) y la tasa
        no se ha actualizado en más de STALE_RATE_HOURS → WARNING.
        """
        from rates.models import ExchangeRate, Currency
        from django.utils.timezone import localtime
        import pytz

        anomalies = []
        tz_bolivia = pytz.timezone('America/La_Paz')
        now_local  = localtime(timezone.now(), tz_bolivia)

        # Solo verificar en horario hábil
        if not (BUSINESS_HOURS_START <= now_local.hour < BUSINESS_HOURS_END):
            return anomalies

        stale_cutoff = timezone.now() - timedelta(hours=STALE_RATE_HOURS)

        bob = Currency.objects.filter(code='BOB').first()
        if not bob:
            return anomalies

        tasas = (ExchangeRate.objects
                 .filter(currency_to=bob, valid_until__isnull=True)
                 .exclude(currency_from=bob)
                 .select_related('currency_from'))

        for t in tasas:
            if t.updated_at < stale_cutoff:
                age_hours = _q(
                    Decimal((timezone.now() - t.updated_at).total_seconds()) / 3600,
                    Decimal('0.1'),
                )
                anomalies.append(_anomaly(
                    rule        = 'RATE_STALE',
                    severity    = 'WARNING',
                    description = (
                        f'{t.currency_from.code} [{t.market_type}]: '
                        f'tasa sin actualizar hace {age_hours} h '
                        f'(última actualización: {t.updated_at:%H:%M})'
                    ),
                    value     = age_hours,
                    threshold = STALE_RATE_HOURS,
                    currency  = t.currency_from.code,
                    details   = {
                        'market_type':  t.market_type,
                        'updated_at':   t.updated_at.isoformat(),
                        'age_hours':    str(age_hours),
                        'rate_id':      t.id,
                    },
                ))

        return anomalies

    # ── Regla 4c: Desviación sobre tasa BCB ──────────────────────────────────

    @staticmethod
    def _check_rate_bcb_deviation() -> list:
        """
        Si la tasa de mercado (paralelo) supera en ≥15 % (WARNING) o
        ≥30 % (CRITICAL) a la tasa oficial BCB → alerta.
        """
        from rates.models import ExchangeRate, Currency

        anomalies = []
        bob = Currency.objects.filter(code='BOB').first()
        if not bob:
            return anomalies

        tasas = (ExchangeRate.objects
                 .filter(currency_to=bob, valid_until__isnull=True)
                 .exclude(currency_from=bob)
                 .exclude(official_rate__isnull=True)
                 .exclude(official_rate=0)
                 .select_related('currency_from'))

        for t in tasas:
            dev_pct = _q(
                (t.sell_rate / t.official_rate - 1) * 100, PCT_Q
            )
            if dev_pct >= RATE_BCB_DEV_CRITICAL_PCT:
                severity = 'CRITICAL'
            elif dev_pct >= RATE_BCB_DEV_WARNING_PCT:
                severity = 'WARNING'
            else:
                continue

            anomalies.append(_anomaly(
                rule        = 'RATE_BCB_DEVIATION',
                severity    = severity,
                description = (
                    f'{t.currency_from.code} [{t.market_type}]: '
                    f'tasa de mercado {dev_pct}% sobre la oficial BCB '
                    f'(mercado {t.sell_rate} vs BCB {t.official_rate})'
                ),
                value     = dev_pct,
                threshold = (RATE_BCB_DEV_CRITICAL_PCT
                             if severity == 'CRITICAL' else RATE_BCB_DEV_WARNING_PCT),
                currency  = t.currency_from.code,
                details   = {
                    'market_type':   t.market_type,
                    'sell_rate':     str(t.sell_rate),
                    'official_rate': str(t.official_rate),
                    'deviation_pct': str(dev_pct),
                    'rate_id':       t.id,
                },
            ))

        return anomalies

    # ── Regla 5: Spread insuficiente ─────────────────────────────────────────

    @staticmethod
    def _check_spread_below_min() -> list:
        """spread_pct < 0.30 % → WARNING (margen insuficiente para cubrir costos)."""
        from rates.models import ExchangeRate, Currency

        anomalies = []
        bob = Currency.objects.filter(code='BOB').first()
        if not bob:
            return anomalies

        tasas = (ExchangeRate.objects
                 .filter(currency_to=bob, valid_until__isnull=True)
                 .exclude(currency_from=bob)
                 .select_related('currency_from'))

        for t in tasas:
            if t.buy_rate == 0:
                continue
            spread_pct = _q((t.sell_rate - t.buy_rate) / t.buy_rate * 100, PCT_Q)
            if spread_pct < SPREAD_MIN_PCT:
                anomalies.append(_anomaly(
                    rule        = 'SPREAD_BELOW_MIN',
                    severity    = 'WARNING',
                    description = (
                        f'{t.currency_from.code} [{t.market_type}]: '
                        f'spread {spread_pct}% < mínimo {SPREAD_MIN_PCT}% — '
                        f'margen insuficiente'
                    ),
                    value     = spread_pct,
                    threshold = SPREAD_MIN_PCT,
                    currency  = t.currency_from.code,
                    details   = {
                        'market_type': t.market_type,
                        'buy_rate':    str(t.buy_rate),
                        'sell_rate':   str(t.sell_rate),
                        'spread_pct':  str(spread_pct),
                        'rate_id':     t.id,
                    },
                ))

        return anomalies

    # ── Regla 6: Concentración de riesgo ─────────────────────────────────────

    @staticmethod
    def _check_exposure(branch=None) -> list:
        """
        Delega en ExposureService.calcular_exposicion() y convierte
        los alert_level WARNING/CRITICAL a anomalías persistibles.
        """
        anomalies = []
        result = ExposureService.calcular_exposicion(branch=branch)

        for d in result.get('divisas', []):
            level = d.get('alert_level', 'OK')
            if level not in ('WARNING', 'CRITICAL'):
                continue
            pct = Decimal(d.get('pct_of_capital', '0'))
            anomalies.append(_anomaly(
                rule        = 'EXPOSURE_HIGH',
                severity    = level,
                description = (
                    f'{d["currency_code"]}: {pct}% de la exposición total '
                    f'(Bs.{d["exposure_bob"]} de Bs.{result["total_exposure_bob"]})'
                ),
                value     = pct,
                threshold = (EXPOSURE_CRITICAL_PCT
                             if level == 'CRITICAL' else EXPOSURE_WARNING_PCT),
                currency  = d['currency_code'],
                branch    = branch,
                details   = {
                    'exposure_bob':       d['exposure_bob'],
                    'total_exposure_bob': result['total_exposure_bob'],
                    'unrealized_pnl_bob': d.get('unrealized_pnl_bob', '0'),
                    'sell_rate_unit':     d.get('sell_rate_unit', '0'),
                    'wac_unit':           d.get('wac_unit', '0'),
                },
            ))

        return anomalies

    # ── Persistencia ──────────────────────────────────────────────────────────

    @staticmethod
    def _persist(anomalies: list) -> int:
        """
        Guarda las anomalías en CapitalAnomalyLog.

        Deduplicación: si ya existe una anomalía no resuelta del mismo
        rule + branch + currency en los últimos 30 minutos, se omite
        (evita spam de filas idénticas en scans frecuentes).

        Retorna el número de filas insertadas.
        """
        from .models import CapitalAnomalyLog
        from django.db import transaction as db_tx

        DEDUP_WINDOW = timedelta(minutes=30)
        inserted = 0
        cutoff   = timezone.now() - DEDUP_WINDOW

        with db_tx.atomic():
            for a in anomalies:
                already = CapitalAnomalyLog.objects.filter(
                    rule     = a['rule'],
                    currency = a.get('currency', ''),
                    branch_id= a.get('branch_id'),
                    resolved = False,
                    created_at__gte = cutoff,
                ).exists()

                if already:
                    continue

                CapitalAnomalyLog.objects.create(
                    rule        = a['rule'],
                    severity    = a['severity'],
                    branch_id   = a.get('branch_id'),
                    currency    = a.get('currency', ''),
                    description = a['description'],
                    value       = Decimal(a['value']),
                    threshold   = Decimal(a['threshold']),
                    details     = a.get('details', {}),
                )
                inserted += 1

        if inserted:
            log.info('ANOMALY_PERSISTED count=%d', inserted)
        return inserted
