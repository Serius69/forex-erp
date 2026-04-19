"""
Tareas Celery para actualización automática de tasas de cambio.

Estructura:
  - update_bcb_rates        → cada 30 min — fuentes BCB oficial + referencial
  - update_digital_rates    → cada 60 min — Takenos, Airtm y similares
  - update_parallel_rates   → cada 20 min — mercado paralelo (dato más volátil)
  - update_all_rates        → orquesta los tres anteriores
  - check_significant_changes (interna) → detecta variaciones > umbral y notifica
"""
from __future__ import annotations
import logging
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from decimal import Decimal

log = logging.getLogger('kapitalya.rates.tasks')

# Retry policy
_RETRY_BACKOFF = [60, 300, 900, 1800, 3600]   # 1m, 5m, 15m, 30m, 1h


# ------------------------------------------------------------------ #
#  Tareas públicas por tipo de mercado                                 #
# ------------------------------------------------------------------ #

@shared_task(
    bind=True,
    acks_late=True,
    max_retries=5,
    name='rates.update_bcb_rates',
)
def update_bcb_rates(self):
    """
    Actualiza tasas desde el Banco Central de Bolivia.
    market_type: official + bcb
    """
    from .fetchers.bcb_fetcher import BCBOfficialFetcher, BCBReferenceFetcher
    from .aggregator import RateAggregator

    log.info("TASK_START rates.update_bcb_rates")
    try:
        results = []
        for cls in (BCBOfficialFetcher, BCBReferenceFetcher):
            results.extend(cls().fetch())

        agg       = RateAggregator()
        aggregated = agg.aggregate(results)
        saved     = agg.save_to_db(aggregated)

        _notify_ws_if_needed(aggregated)
        _run_alert_generator_for_branches(list(aggregated.keys()))
        log.info("TASK_DONE rates.update_bcb_rates saved=%d", saved)
        return {'success': True, 'saved': saved}

    except Exception as exc:
        delay = _RETRY_BACKOFF[min(self.request.retries, len(_RETRY_BACKOFF) - 1)]
        log.error("TASK_ERROR rates.update_bcb_rates error=%s retry_in=%ds", exc, delay)
        raise self.retry(exc=exc, countdown=delay)


@shared_task(
    bind=True,
    acks_late=True,
    max_retries=5,
    name='rates.update_digital_rates',
)
def update_digital_rates(self):
    """
    Actualiza tasas de plataformas digitales (Takenos, Airtm).
    market_type: digital
    """
    from .fetchers.digital_fetcher import TakenosFetcher, AirtmFetcher
    from .aggregator import RateAggregator

    log.info("TASK_START rates.update_digital_rates")
    try:
        results = []
        for cls in (TakenosFetcher, AirtmFetcher):
            results.extend(cls().fetch())

        agg       = RateAggregator()
        aggregated = agg.aggregate(results)
        saved     = agg.save_to_db(aggregated)

        _notify_ws_if_needed(aggregated)
        _run_alert_generator_for_branches(list(aggregated.keys()))
        log.info("TASK_DONE rates.update_digital_rates saved=%d", saved)
        return {'success': True, 'saved': saved}

    except Exception as exc:
        delay = _RETRY_BACKOFF[min(self.request.retries, len(_RETRY_BACKOFF) - 1)]
        log.error("TASK_ERROR rates.update_digital_rates error=%s retry_in=%ds", exc, delay)
        raise self.retry(exc=exc, countdown=delay)


@shared_task(
    bind=True,
    acks_late=True,
    max_retries=5,
    name='rates.update_parallel_rates',
)
def update_parallel_rates(self):
    """
    Actualiza tasas del mercado paralelo.
    market_type: parallel
    """
    from .fetchers.parallel_scraper import ParallelMarketFetcher
    from .aggregator import RateAggregator

    log.info("TASK_START rates.update_parallel_rates")
    try:
        results   = ParallelMarketFetcher().fetch()
        agg       = RateAggregator()
        aggregated = agg.aggregate(results)
        saved     = agg.save_to_db(aggregated)

        _notify_ws_if_needed(aggregated)
        _run_alert_generator_for_branches(list(aggregated.keys()))
        log.info("TASK_DONE rates.update_parallel_rates saved=%d", saved)
        return {'success': True, 'saved': saved}

    except Exception as exc:
        delay = _RETRY_BACKOFF[min(self.request.retries, len(_RETRY_BACKOFF) - 1)]
        log.error("TASK_ERROR rates.update_parallel_rates error=%s retry_in=%ds", exc, delay)
        raise self.retry(exc=exc, countdown=delay)


@shared_task(
    bind=True,
    acks_late=True,
    max_retries=3,
    name='rates.update_all_rates',
)
def update_all_rates(self):
    """
    Orquesta la actualización de TODAS las fuentes.
    Útil para el primer arranque o refresco forzado desde el admin.
    """
    from .aggregator import RateAggregator

    log.info("TASK_START rates.update_all_rates")
    try:
        agg        = RateAggregator()
        aggregated = agg.collect_and_aggregate()
        saved      = agg.save_to_db(aggregated)

        _check_significant_changes(aggregated)
        _notify_ws_if_needed(aggregated)
        _run_alert_generator_for_branches(list(aggregated.keys()))

        log.info("TASK_DONE rates.update_all_rates saved=%d", saved)
        return {'success': True, 'saved': saved, 'currencies': list(aggregated.keys())}

    except Exception as exc:
        delay = _RETRY_BACKOFF[min(self.request.retries, 2)]
        log.error("TASK_ERROR rates.update_all_rates error=%s retry_in=%ds", exc, delay)
        raise self.retry(exc=exc, countdown=delay)


# ------------------------------------------------------------------ #
#  Backward-compatible wrapper (legado — mantener hasta refactor)      #
# ------------------------------------------------------------------ #

@shared_task(name='rates.update_exchange_rates')
def update_exchange_rates():
    """Legado: delega en update_all_rates."""
    return update_all_rates.delay()


@shared_task(
    bind=True,
    acks_late=True,
    max_retries=2,
    name='rates.mark_primary_rates',
)
def mark_primary_rates_task(self):
    """
    Re-evalúa y marca la tasa is_primary=True para cada par de divisas activo.
    Ejecutar después de cualquier actualización de tasas.
    Criterio: mayor confianza + NOT INFERENCE + mayor prioridad de mercado.
    """
    from .models import Currency, ExchangeRate
    from .aggregator import MARKET_PRIORITY
    from decimal import Decimal as _D

    log.info('TASK_START rates.mark_primary_rates')
    try:
        bob        = Currency.objects.get(code='BOB')
        currencies = Currency.objects.filter(is_active=True).exclude(code='BOB')
        marked     = 0

        for cur in currencies:
            active = list(
                ExchangeRate.objects
                .filter(
                    currency_from    = cur,
                    currency_to      = bob,
                    valid_until__isnull = True,
                )
                .order_by('-confidence', '-valid_from')
            )

            if not active:
                continue

            # Clear existing primary
            ExchangeRate.objects.filter(
                currency_from    = cur,
                currency_to      = bob,
                is_primary       = True,
            ).update(is_primary=False)

            eligible = [r for r in active if r.source_method != 'INFERENCE']
            if not eligible:
                eligible = active

            def _score(r):
                mp = MARKET_PRIORITY.get(r.market_type, 0)
                return float(r.confidence) + mp * 0.1

            best = max(eligible, key=_score)
            ExchangeRate.objects.filter(pk=best.pk).update(is_primary=True)
            marked += 1
            log.debug(
                'PRIMARY_MARKED %s market=%s conf=%.2f method=%s id=%d',
                cur.code, best.market_type,
                float(best.confidence), best.source_method, best.pk,
            )

        # Invalidate primary rate caches
        try:
            from django.core.cache import cache
            for cur in currencies:
                cache.delete(f'primary_rate_{cur.code}_BOB')
                cache.delete(f'rates_summary_{cur.code}_BOB')
        except Exception:
            pass

        log.info('TASK_DONE rates.mark_primary_rates marked=%d', marked)
        return {'marked': marked}

    except Exception as exc:
        delay = _RETRY_BACKOFF[min(self.request.retries, 1)]
        log.error('TASK_ERROR rates.mark_primary_rates error=%s', exc)
        raise self.retry(exc=exc, countdown=delay)


@shared_task(
    bind=True,
    acks_late=True,
    max_retries=2,
    name='rates.check_source_divergence',
)
def check_source_divergence_task(self):
    """
    Verifica divergencias entre fuentes de tasas.
    Genera alerta si la desviación estándar supera MAX_DIVERGENCE_PCT.
    """
    from .exchange_rate_service import ExchangeRateService

    log.info('TASK_START rates.check_source_divergence')
    try:
        service     = ExchangeRateService()
        divergences = service.detect_divergences()

        if divergences:
            _send_divergence_alert(divergences)

        log.info('TASK_DONE rates.check_source_divergence divergences=%d', len(divergences))
        return {'divergences': len(divergences), 'details': divergences}

    except Exception as exc:
        log.error('TASK_ERROR rates.check_source_divergence error=%s', exc)
        raise self.retry(exc=exc, countdown=60)


def _send_divergence_alert(divergences: list[dict]) -> None:
    """Envía alerta cuando hay divergencia significativa entre fuentes."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        layer = get_channel_layer()
        if layer:
            async_to_sync(layer.group_send)('rates_updates', {
                'type':        'rate_divergence_alert',
                'divergences': divergences,
                'count':       len(divergences),
            })
    except Exception as exc:
        log.debug('DIVERGENCE_WS_SKIP error=%s', exc)

    try:
        from django.core.mail import send_mail
        from django.conf import settings as _settings
        lines = [
            f"[{d['severity']}] {d['currency']}: "
            f"divergencia {d['divergence_pct']}% entre {d['source_count']} fuentes "
            f"(min={d['min']:.4f} max={d['max']:.4f})"
            for d in divergences
        ]
        send_mail(
            subject       = 'Kapitalya — Alerta: Divergencia entre fuentes de tasas',
            message       = 'Divergencias detectadas:\n\n' + '\n'.join(lines),
            from_email    = getattr(_settings, 'DEFAULT_FROM_EMAIL', 'noreply@kapitalya.bo'),
            recipient_list = getattr(_settings, 'RATE_ALERT_EMAILS', ['admin@kapitalya.bo']),
            fail_silently  = True,
        )
    except Exception as exc:
        log.debug('DIVERGENCE_EMAIL_SKIP error=%s', exc)


@shared_task(
    bind=True,
    acks_late=True,
    max_retries=3,
    name='rates.fetch_binance_p2p',
)
def fetch_binance_p2p_task(self):
    """
    Consulta Binance P2P para obtener precio USDT/BOB en tiempo real.
    Programar cada 5 minutos en Celery Beat.
    """
    log.info('TASK_START rates.fetch_binance_p2p')
    try:
        from .fetchers.binance_p2p import fetch_binance_p2p
        result = fetch_binance_p2p()

        if not result.get('from_cache'):
            # Notificar WebSocket con las tasas actualizadas
            try:
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync
                from .models import ExchangeRate, Currency

                layer = get_channel_layer()
                if layer:
                    bob = Currency.objects.get(code='BOB')
                    rates_snapshot = {}
                    for r in (ExchangeRate.objects
                              .filter(currency_to=bob, valid_until__isnull=True)
                              .select_related('currency_from')):
                        code  = r.currency_from.code
                        mtype = r.market_type
                        key   = f'{code}_{mtype}' if mtype != 'parallel' else code
                        rates_snapshot[key] = {
                            'code':  code, 'market_type': mtype,
                            'buy':   float(r.buy_rate),
                            'sell':  float(r.sell_rate),
                            'official': float(r.official_rate),
                        }
                    async_to_sync(layer.group_send)(
                        'rates_updates',
                        {'type': 'rates_update', 'rates': rates_snapshot},
                    )
            except Exception as ws_err:
                log.debug('BINANCE_WS_NOTIFY_SKIP %s', ws_err)

        if not result.get('from_cache'):
            _run_alert_generator_for_branches(['USDT'])

        log.info('TASK_DONE rates.fetch_binance_p2p buy=%s sell=%s from_cache=%s',
                 result['buy'], result['sell'], result['from_cache'])
        return {'success': True, **{k: str(v) for k, v in result.items()}}

    except Exception as exc:
        delay = _RETRY_BACKOFF[min(self.request.retries, 2)]
        log.error('TASK_ERROR rates.fetch_binance_p2p error=%s retry_in=%ds', exc, delay)
        raise self.retry(exc=exc, countdown=delay)


# ------------------------------------------------------------------ #
#  Helpers internos                                                    #
# ------------------------------------------------------------------ #

def _notify_ws_if_needed(aggregated) -> None:
    """Publica tasas actualizadas al WebSocket si hay consumidores conectados."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        layer = get_channel_layer()
        if layer is None:
            return

        payload = {
            'type':  'rate_update',
            'rates': {
                code: {
                    'buy':         float(r.buy_rate),
                    'sell':        float(r.sell_rate),
                    'official':    float(r.official_rate),
                    'market_type': r.market_type,
                    'scale_factor': r.scale_factor,
                    'confidence':  r.confidence,
                    'sources':     r.sources,
                }
                for code, r in aggregated.items()
            },
        }
        async_to_sync(layer.group_send)('rates_updates', payload)
        log.debug("WS_NOTIFY_SENT currencies=%d", len(aggregated))
    except Exception as exc:
        log.debug("WS_NOTIFY_SKIP error=%s", exc)


def _run_alert_generator_for_branches(currencies: list[str]) -> None:
    """
    Ejecuta AlertGenerator.generar_alertas() para todas las sucursales activas
    y cada moneda recién actualizada.  Fire-and-forget: errores no interrumpen
    el flujo principal de actualización de tasas.
    """
    try:
        from alerts.services import AlertGenerator
        from users.models import Branch
        branches = Branch.objects.filter(is_active=True)
        for branch in branches:
            for code in currencies:
                if code == 'BOB':
                    continue
                try:
                    AlertGenerator.generar_alertas(branch, currency=code)
                except Exception as exc:
                    log.debug('ALERT_GEN_SKIP branch=%s currency=%s err=%s', branch, code, exc)
    except Exception as exc:
        log.debug('ALERT_GEN_FOR_BRANCHES_FAIL err=%s', exc)


def _check_significant_changes(aggregated) -> None:
    """
    Compara tasas nuevas contra las anteriores en DB.

    Phase 8 rules:
      - Alert if any currency changes > 5% in buy or sell rate.
      - Always alert if source_method is INFERENCE (no real data available).
    Threshold raised from 3% → 5% per financial compliance review.
    """
    from .models import Currency, ExchangeRate

    VELOCITY_THRESHOLD = Decimal('0.05')   # 5% — Phase 8
    alerts = []

    for code, new_rate in aggregated.items():
        # ── Phase 8: Always warn on INFERENCE rates ───────────────────────────
        if getattr(new_rate, 'source_method', None) == 'INFERENCE':
            alerts.append({
                'currency':    code,
                'market':      new_rate.market_type,
                'previous':    None,
                'new':         float(new_rate.buy_rate),
                'pct':         None,
                'reason':      'INFERENCE — tasa estimada, sin fuente en tiempo real',
                'severity':    'WARNING',
            })

        try:
            currency = Currency.objects.get(code=code)
            bob      = Currency.objects.get(code='BOB')
            prev     = (
                ExchangeRate.objects
                .filter(
                    currency_from       = currency,
                    currency_to         = bob,
                    market_type         = new_rate.market_type,
                    valid_until__isnull = False,
                )
                .order_by('-valid_until')
                .first()
            )
            if not prev or prev.buy_rate <= 0:
                continue

            buy_pct  = abs(new_rate.buy_rate  - prev.buy_rate)  / prev.buy_rate
            sell_pct = abs(new_rate.sell_rate - prev.sell_rate) / prev.sell_rate if prev.sell_rate > 0 else Decimal('0')
            max_pct  = max(buy_pct, sell_pct)

            if max_pct > VELOCITY_THRESHOLD:
                alerts.append({
                    'currency': code,
                    'market':   new_rate.market_type,
                    'previous': float(prev.buy_rate),
                    'new':      float(new_rate.buy_rate),
                    'pct':      float(max_pct * 100),
                    'reason':   f'Variación > {float(VELOCITY_THRESHOLD)*100:.0f}%',
                    'severity': 'CRITICAL' if max_pct > Decimal('0.10') else 'WARNING',
                })
        except Exception:
            pass

    if alerts:
        _send_rate_change_alert(alerts)


def _send_rate_change_alert(alerts: list[dict]) -> None:
    """Envía email y Telegram cuando hay cambios significativos en tasas."""
    lines = []
    for a in alerts:
        prev_str = f"{a['previous']:.4f} → " if a.get('previous') is not None else ''
        pct_str  = f"({a['pct']:.1f}% cambio)" if a.get('pct') is not None else ''
        reason   = a.get('reason', '')
        severity = a.get('severity', 'WARNING')
        lines.append(
            f"[{severity}] {a['currency']} ({a['market']}): "
            f"{prev_str}{a['new']:.4f} {pct_str} — {reason}"
        )
    body = "Alertas de tasas de cambio detectadas:\n\n" + "\n".join(lines)

    try:
        send_mail(
            subject   = 'Kapitalya — Alerta: Variación significativa en tasas',
            message   = body,
            from_email= getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@kapitalya.bo'),
            recipient_list = getattr(settings, 'RATE_ALERT_EMAILS', ['admin@kapitalya.bo']),
            fail_silently  = True,
        )
        log.info("RATE_ALERT_EMAIL_SENT alerts=%d", len(alerts))
    except Exception as exc:
        log.warning("RATE_ALERT_EMAIL_FAILED error=%s", exc)

    # Telegram: una alerta por cada variación sospechosa detectada
    try:
        from services.notifications.telegram import alert_suspicious_rate
        for a in alerts:
            alert_suspicious_rate(
                currency=a['currency'],
                market=a['market'],
                previous=a['previous'],
                new=a['new'],
                pct_change=a['pct'],
            )
    except Exception as exc:
        log.debug("RATE_ALERT_TELEGRAM_FAILED error=%s", exc)


# ------------------------------------------------------------------ #
#  Motor de Precios AI                                                 #
# ------------------------------------------------------------------ #

@shared_task(
    bind=True,
    acks_late=True,
    max_retries=2,
    name='rates.update_ai_pricing',
)
def update_ai_pricing_task(self):
    """
    Ejecuta el motor de precios AI para todas las divisas activas.
    Se programa cada 15 minutos en Celery Beat (después de fetch_binance_p2p).
    """
    from rates.models import Currency
    from rates.ai_pricing import AIPricingEngine

    log.info('TASK_START rates.update_ai_pricing')
    try:
        engine = AIPricingEngine()
        # Divisas activas que no sean BOB
        currencies = Currency.objects.filter(is_active=True).exclude(code='BOB')
        results = []
        for currency in currencies:
            try:
                result = engine.suggest_and_save(currency.code, trigger='scheduled')
                results.append({
                    'currency': currency.code,
                    'suggested_buy':  float(result['suggested_buy']),
                    'suggested_sell': float(result['suggested_sell']),
                    'spread_pct':     float(result['suggested_spread_pct']),
                })
                log.info(
                    'AI_PRICING %s: buy=%s sell=%s spread=%.2f%%',
                    currency.code, result['suggested_buy'],
                    result['suggested_sell'], float(result['suggested_spread_pct']),
                )
            except Exception as exc:
                log.warning('AI_PRICING_SKIP %s: %s', currency.code, exc)

        # Notificar via WebSocket
        _ws_send_ai_pricing(results)

        log.info('TASK_DONE rates.update_ai_pricing currencies=%d', len(results))
        return {'currencies_processed': len(results), 'results': results}

    except Exception as exc:
        delay = _RETRY_BACKOFF[min(self.request.retries, len(_RETRY_BACKOFF) - 1)]
        log.error('TASK_ERROR rates.update_ai_pricing error=%s retry_in=%ds', exc, delay)
        raise self.retry(exc=exc, countdown=delay)


def _ws_send_ai_pricing(results: list[dict]) -> None:
    """Publica sugerencias de precios AI al WebSocket."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)('rates_updates', {
            'type':       'ai_pricing_update',
            'suggestions': results,
        })
    except Exception as exc:
        log.debug('WS_AI_PRICING_SKIP error=%s', exc)


# ------------------------------------------------------------------ #
#  Alertas Inteligentes                                                #
# ------------------------------------------------------------------ #

@shared_task(
    bind=True,
    acks_late=True,
    max_retries=0,
    name='rates.check_smart_alerts',
)
def check_smart_alerts_task(self):
    """
    Motor de alertas inteligentes. Verifica:
    1. Caída de capital total > 5% vs ayer
    2. P&L diario negativo
    3. Tasa paralela subió > 2% en última hora
    4. Inventario crítico (< mínimo)
    5. Spread muy bajo (< 0.2%)
    """
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    from django.utils import timezone as tz

    log.info('TASK_START rates.check_smart_alerts')
    alerts = []

    # ── 1. Caída de capital ───────────────────────────────────────────────────
    try:
        from capital.models import CapitalSnapshot
        today = tz.now().date()
        snap_today     = CapitalSnapshot.objects.filter(fecha=today).order_by('-created_at').first()
        snap_yesterday = CapitalSnapshot.objects.filter(fecha=today - __import__('datetime').timedelta(days=1)).order_by('-created_at').first()
        if snap_today and snap_yesterday and snap_yesterday.total_bob > 0:
            pct_change = float((snap_today.total_bob - snap_yesterday.total_bob) / snap_yesterday.total_bob * 100)
            if pct_change < -5:
                alerts.append({
                    'type': 'CAPITAL_DROP',
                    'severity': 'CRITICAL' if pct_change < -10 else 'WARNING',
                    'message': f'Capital total cayó {abs(pct_change):.1f}% vs ayer',
                    'value': pct_change,
                })
    except Exception as exc:
        log.debug('Capital alert check failed: %s', exc)

    # ── 2. P&L diario negativo ────────────────────────────────────────────────
    try:
        from analytics.models import PnLDailySnapshot
        today = tz.now().date()
        pnl_today = PnLDailySnapshot.objects.filter(fecha=today)
        for snap in pnl_today:
            if snap.ganancia_neta_bob < 0:
                alerts.append({
                    'type': 'PNL_NEGATIVE',
                    'severity': 'WARNING',
                    'message': f'P&L negativo hoy: {snap.ganancia_neta_bob} BOB',
                    'value': float(snap.ganancia_neta_bob),
                    'branch': str(snap.branch) if snap.branch else 'Global',
                })
    except Exception as exc:
        log.debug('P&L alert check failed: %s', exc)

    # ── 3. Salto de tasa paralela > 2% en 1h ─────────────────────────────────
    try:
        from rates.models import ExchangeRate, Currency
        one_hour_ago = tz.now() - __import__('datetime').timedelta(hours=1)
        currencies = Currency.objects.filter(is_active=True).exclude(code='BOB')
        bob = Currency.objects.get(code='BOB')
        for cur in currencies:
            rates_1h = (ExchangeRate.objects
                        .filter(currency_from=cur, currency_to=bob,
                                market_type__in=('paralelo_digital', 'paralelo_fisico_empresa'),
                                valid_from__gte=one_hour_ago)
                        .order_by('valid_from'))
            if rates_1h.count() >= 2:
                oldest = rates_1h.first().sell_rate
                newest = rates_1h.last().sell_rate
                if oldest > 0:
                    pct = float((newest - oldest) / oldest * 100)
                    if abs(pct) > 2:
                        alerts.append({
                            'type': 'RATE_SPIKE',
                            'severity': 'WARNING',
                            'message': f'{cur.code}: TC paralelo {"subió" if pct > 0 else "bajó"} {abs(pct):.1f}% en 1h',
                            'currency': cur.code,
                            'value': pct,
                        })
    except Exception as exc:
        log.debug('Rate spike check failed: %s', exc)

    # ── 4. Inventario crítico ─────────────────────────────────────────────────
    try:
        from inventory.models import CurrencyInventory
        critical = CurrencyInventory.objects.filter(
            physical_balance__lt=__import__('django.db.models', fromlist=['F']).F('minimum_stock')
        ).select_related('currency', 'branch')
        for inv in critical[:10]:
            alerts.append({
                'type': 'INVENTORY_CRITICAL',
                'severity': 'WARNING',
                'message': f'{inv.currency.code} en {inv.branch}: stock {inv.physical_balance} < mínimo {inv.minimum_stock}',
                'currency': inv.currency.code,
                'value': float(inv.physical_balance),
            })
    except Exception as exc:
        log.debug('Inventory alert check failed: %s', exc)

    # ── Enviar alertas por WebSocket ──────────────────────────────────────────
    if alerts:
        try:
            layer = get_channel_layer()
            if layer:
                async_to_sync(layer.group_send)('rates_updates', {
                    'type':   'smart_alerts',
                    'alerts': alerts,
                    'count':  len(alerts),
                })
        except Exception as exc:
            log.debug('Smart alerts WS send failed: %s', exc)

    log.info('TASK_DONE rates.check_smart_alerts alerts=%d', len(alerts))
    return {'alerts': len(alerts), 'details': alerts}
