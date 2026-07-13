"""
Tareas Celery para actualización automática de tasas de cambio.

Estructura:
  - fetch_dolar_blue_bolivia → cada 15 min — dolarbluebolivia.click (fuente única)
  - update_digital_rates    → cada 60 min — Takenos, Airtm y similares
  - update_parallel_rates   → cada 20 min — mercado paralelo P2P
  - update_all_rates        → orquesta todos los fetchers
  - check_significant_changes (interna) → detecta variaciones > umbral y notifica

Fuente única: mercado paralelo boliviano. BCB eliminado.
"""
from __future__ import annotations
import logging
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
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
    reject_on_worker_lost=True,
    max_retries=3,
    soft_time_limit=60,
    time_limit=90,
    name='rates.fetch_parallel_rate',
)
def fetch_parallel_rate(self):
    """
    Obtiene tasa paralela USD/BOB desde dolarbluebolivia.click cada 15 minutos.
    Guarda como ExchangeRate con market_type='paralelo_digital', source='dolarbluebolivia_click'.
    Invalida caché de tasas al guardar.
    """
    from django.utils import timezone
    from django.core.cache import cache
    from .scrapers.dolar_blue_bolivia import scrape_parallel_rate
    from .models import Currency, ExchangeRate

    log.info('TASK_START rates.fetch_parallel_rate')
    try:
        data = scrape_parallel_rate()

        if not data.get('mid'):
            log.warning('TASK_WARN rates.fetch_parallel_rate — no mid rate extracted')
            return {'success': False, 'reason': 'no_mid_rate'}

        usd = Currency.objects.filter(code='USD').first()
        bob = Currency.objects.filter(code='BOB').first()
        if not usd or not bob:
            log.error('TASK_ERROR rates.fetch_parallel_rate — missing USD/BOB currencies')
            return {'success': False, 'reason': 'missing_currencies'}

        now = timezone.now()

        # Cerrar tasa activa anterior
        ExchangeRate.objects.filter(
            currency_from=usd,
            currency_to=bob,
            market_type='paralelo_digital',
            source='dolarbluebolivia_click',
            valid_until__isnull=True,
        ).update(valid_until=now)

        # Crear nueva tasa
        rate = ExchangeRate.objects.create(
            currency_from = usd,
            currency_to   = bob,
            market_type   = 'paralelo_digital',
            source        = 'dolarbluebolivia_click',
            official_rate = data['mid'],
            buy_rate      = data['buy'] or data['mid'],
            sell_rate     = data['sell'] or data['mid'],
            valid_from    = now,
            valid_until   = None,
            source_method = 'SCRAP',
            source_url    = data['source_url'],
            fetched_at    = now,
            confidence    = Decimal('0.850'),
            is_validated  = False,
        )

        # Invalidar cachés relacionadas
        for pattern in ('primary_rate_USD_BOB', 'rates_summary_USD_BOB', 'parallel_rate:*'):
            try:
                cache.delete(pattern)
            except Exception:
                pass

        _run_alert_generator_for_branches(['USD'])

        log.info(
            'TASK_DONE rates.fetch_parallel_rate id=%d buy=%s sell=%s mid=%s',
            rate.pk, data['buy'], data['sell'], data['mid'],
        )
        return {
            'success': True,
            'rate_id': rate.pk,
            'buy':  str(data['buy']),
            'sell': str(data['sell']),
            'mid':  str(data['mid']),
        }

    except Exception as exc:
        delay = _RETRY_BACKOFF[min(self.request.retries, 2)]
        log.error('TASK_ERROR rates.fetch_parallel_rate error=%s retry_in=%ds', exc, delay)
        raise self.retry(exc=exc, countdown=delay)


@shared_task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=5,
    soft_time_limit=120,
    time_limit=150,
    name='rates.update_digital_rates',
)
def update_digital_rates(self):
    """
    Actualiza tasas de plataformas digitales (Takenos, Airtm).
    market_type: digital
    """
    from .fetchers.digital_fetcher import TakenosFetcher, AirtmFetcher
    from .fetchers.dolar_blue_bolivia import DolarBlueBoliviaFetcher
    from .aggregator import RateAggregator

    log.info("TASK_START rates.update_digital_rates")
    try:
        results = []
        for cls in (TakenosFetcher, AirtmFetcher, DolarBlueBoliviaFetcher):
            results.extend(cls().fetch())

        agg       = RateAggregator()
        agg.save_raw_to_db(results)
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
    reject_on_worker_lost=True,
    max_retries=5,
    soft_time_limit=120,
    time_limit=150,
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
        agg.save_raw_to_db(results)
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
    reject_on_worker_lost=True,
    max_retries=3,
    soft_time_limit=180,
    time_limit=240,
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
#  FX Engine — motor paralelo real (principal en producción)           #
# ------------------------------------------------------------------ #

@shared_task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
    soft_time_limit=90,
    time_limit=120,
    name='rates.run_fx_engine',
)
def run_fx_engine_task(self):
    """
    Ejecuta el FX Engine de producción:
      1. Fetch paralelo de Binance P2P, Bitget, Bybit, Airtm, Eldorado, Wallbit, SaldoAR
      2. Limpieza IQR + cálculo de mercado
      3. Aplicación de márgenes de negocio + auto-profit
      4. Variantes de efectivo (USD_LOOSE, USD_SMALL, PEN_COINS)
      5. Guardado en DB + emisión WebSocket

    Programar cada 5 minutos en Celery Beat.
    """
    from .fx_engine import run_engine

    log.info('TASK_START rates.run_fx_engine')
    try:
        result = run_engine(save=True, emit=True)
        currencies = list(result.rates.keys())
        variants   = list(result.variants.keys())

        _run_alert_generator_for_branches(currencies)

        log.info(
            'TASK_DONE rates.run_fx_engine currencies=%d variants=%d',
            len(currencies), len(variants),
        )
        return {
            'success':    True,
            'currencies': currencies,
            'variants':   variants,
            'rates': {
                code: r.to_dict() for code, r in result.rates.items()
            },
        }

    except Exception as exc:
        delay = _RETRY_BACKOFF[min(self.request.retries, 2)]
        log.error('TASK_ERROR rates.run_fx_engine error=%s retry_in=%ds', exc, delay)
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
    reject_on_worker_lost=True,
    max_retries=3,
    soft_time_limit=45,
    time_limit=60,
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
                            'mid':   float(r.avg_rate or (r.buy_rate + r.sell_rate) / 2),
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


@shared_task(
    bind=True,
    acks_late=True,
    max_retries=3,
    name='rates.fetch_dolar_blue_bolivia',
)
def fetch_dolar_blue_bolivia_task(self):
    """
    Scraping de DolarBlueBolivia — referencia del mercado paralelo boliviano.
    URL: https://www.dolarbluebolivia.click/
    Programar cada 15 minutos en Celery Beat.

    Extrae: USD/BOB paralelo + oficial, 8 exchanges P2P, 7 cross rates regionales.
    """
    log.info('TASK_START rates.fetch_dolar_blue_bolivia')
    try:
        from .fetchers.dolar_blue_bolivia import DolarBlueBoliviaFetcher
        from .aggregator import RateAggregator

        results = DolarBlueBoliviaFetcher().fetch()

        if not results:
            log.warning('TASK_DONE rates.fetch_dolar_blue_bolivia — no rates fetched (site may be down)')
            return {'success': False, 'reason': 'no_rates_from_site'}

        # Persistir todas las tasas (exchanges + cross rates) vía el agregador
        agg  = RateAggregator()
        agg.save_raw_to_db(results)
        agg_results = agg.aggregate(results)
        saved = agg.save_to_db(agg_results)

        # Tasa principal para el log
        main = next((r for r in results if r.source_name == 'DOLARBLUE_BO'), results[0])
        currencies = list({r.currency_code for r in results})
        exchanges  = [r.source_name for r in results if r.source_name.startswith('DOLARBLUE_') and r.currency_code == 'USD']

        _run_alert_generator_for_branches(currencies)
        log.info(
            'TASK_DONE rates.fetch_dolar_blue_bolivia buy=%s sell=%s '
            'total=%d saved=%d currencies=%s exchanges=%d',
            main.buy_rate, main.sell_rate,
            len(results), saved, currencies, len(exchanges),
        )
        return {
            'success':    True,
            'buy':        str(main.buy_rate),
            'sell':       str(main.sell_rate),
            'total':      len(results),
            'saved':      saved,
            'currencies': currencies,
        }

    except Exception as exc:
        delay = _RETRY_BACKOFF[min(self.request.retries, 2)]
        log.error('TASK_ERROR rates.fetch_dolar_blue_bolivia error=%s retry_in=%ds', exc, delay)
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
                    'mid':         float((r.buy_rate + r.sell_rate) / 2),
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


# Debounce del fan-out de alertas (auditoría #27).
#   Las ~7 tasks de tasas de abajo se disparan casi simultáneamente (cada 5-60 min) y
#   antes cada una barría, síncrona y con un subconjunto DISTINTO de divisas, todo el
#   motor de alertas (O(sucursales × divisas)). Ahora, en vez de ejecutar ese doble
#   bucle inline, encolan UNA sola `alerts.evaluate_all` (que cubre la UNIÓN de todas
#   las divisas activas) a lo sumo una vez por ventana de _ALERT_DEBOUNCE_TTL segundos.
#
#   Elección de N=45 s: coalesce la ráfaga de tasks casi-simultáneas en una sola
#   evaluación completa sin sacrificar frescura relevante — el propio motor deduplica
#   cada alerta 30 min (AlertGenerator.DEDUP_MINUTES), así que re-evaluar más seguido
#   que ~cada minuto casi nunca produce alertas nuevas; y como la tarea consolidada
#   cubre TODAS las divisas, el debounce NO pierde ninguna (a diferencia de un debounce
#   por-task, donde saltarse binance perdería USDT). Trade-off: en el peor caso una
#   alerta se retrasa <45 s respecto al modelo síncrono anterior.
_ALERT_DEBOUNCE_KEY = 'alerts_eval_debounce'
_ALERT_DEBOUNCE_TTL = 45   # segundos


def _run_alert_generator_for_branches(currencies: list[str] | None = None) -> None:
    """
    Encola (con debounce) el barrido consolidado del motor de alertas.

    Antes ejecutaba, síncrono e inline, `AlertGenerator.generar_alertas()` para cada
    sucursal activa × cada `currency` recién actualizada. Ahora delega en la tarea
    Celery única `alerts.evaluate_all`, que cubre la UNIÓN de TODAS las divisas activas
    (no el subconjunto `currencies` de esta task) — por eso el parámetro `currencies`
    ya no se usa y solo se conserva por compatibilidad con los call-sites existentes.

    Debounce: `cache.add()` deja pasar solo la PRIMERA de las ~7 tasks casi-simultáneas
    dentro de la ventana; el resto son no-ops. Fire-and-forget: cualquier fallo aquí no
    interrumpe el flujo de actualización de tasas.
    """
    try:
        from django.core.cache import cache
        from alerts.tasks import evaluate_all_alerts
        # Solo la primera task de la ventana consigue el lock → encola el barrido único.
        if cache.add(_ALERT_DEBOUNCE_KEY, 1, _ALERT_DEBOUNCE_TTL):
            evaluate_all_alerts.delay()
    except Exception as exc:
        log.debug('ALERT_GEN_DEBOUNCE_FAIL err=%s', exc)


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
#  Snapshot diario de tasas                                           #
# ------------------------------------------------------------------ #

@shared_task(
    bind=True,
    acks_late=True,
    max_retries=2,
    name='rates.create_daily_snapshot',
)
def create_daily_snapshot_task(self):
    """
    Captura el estado actual del mercado de divisas y lo guarda como
    ExchangeRateSnapshot. Programar al cierre de operaciones (~18:00 BOT).
    """
    from django.utils import timezone as tz
    from .models import Currency, ExchangeRate, ExchangeRateSnapshot
    from decimal import Decimal as _D

    log.info('TASK_START rates.create_daily_snapshot')
    try:
        today = tz.now().date()
        bob   = Currency.objects.get(code='BOB')
        currencies = Currency.objects.filter(is_active=True, use_exchange_rate=True).exclude(code='BOB')

        aggregated_data: dict = {}
        source_count    = 0
        anomaly_count   = 0
        max_spread_pct  = _D('0')
        best_source     = 'unknown'
        best_confidence = _D('0')

        for cur in currencies:
            rate = (ExchangeRate.objects
                    .filter(
                        currency_from=cur,
                        currency_to=bob,
                        valid_until__isnull=True,
                    )
                    .order_by('-confidence', '-valid_from')
                    .first())
            if not rate:
                continue

            spread_pct = _D('0')
            if rate.buy_rate > 0:
                spread_pct = ((rate.sell_rate - rate.buy_rate) / rate.buy_rate * 100)

            aggregated_data[cur.code] = {
                'buy':          float(rate.buy_rate),
                'sell':         float(rate.sell_rate),
                'avg':          float(rate.avg_rate or (rate.buy_rate + rate.sell_rate) / 2),
                'spread_pct':   float(spread_pct),
                'confidence':   float(rate.confidence),
                'source':       rate.source or '',
                'market_type':  rate.market_type,
                'source_method': rate.source_method,
                'source_url':   rate.source_url or '',
                'updated_at':   rate.valid_from.isoformat() if rate.valid_from else '',
            }
            source_count += 1

            if spread_pct > max_spread_pct:
                max_spread_pct = spread_pct
            if rate.confidence > best_confidence:
                best_confidence = rate.confidence
                best_source     = rate.source or rate.source_method

            # Conteo de anomalías (spread > 5% o confianza < 0.7)
            if spread_pct > _D('5') or rate.confidence < _D('0.70'):
                anomaly_count += 1

        usd_data = aggregated_data.get('USD', {})
        eur_data = aggregated_data.get('EUR', {})

        status = (
            'complete' if source_count >= len(list(currencies))
            else 'degraded' if source_count == 0
            else 'partial'
        )

        snapshot, created = ExchangeRateSnapshot.objects.update_or_create(
            date=today,
            defaults={
                'status':          status,
                'aggregated_data': aggregated_data,
                'best_source':     best_source,
                'avg_usd_buy':     _D(str(usd_data['buy']))  if usd_data else None,
                'avg_usd_sell':    _D(str(usd_data['sell'])) if usd_data else None,
                'max_spread_pct':  max_spread_pct.quantize(_D('0.001')),
                'source_count':    source_count,
                'anomaly_count':   anomaly_count,
                'close_usd_buy':   _D(str(usd_data['buy']))  if usd_data else None,
                'close_usd_sell':  _D(str(usd_data['sell'])) if usd_data else None,
                'close_eur_buy':   _D(str(eur_data['buy']))  if eur_data else None,
                'close_eur_sell':  _D(str(eur_data['sell'])) if eur_data else None,
            },
        )

        action = 'CREATED' if created else 'UPDATED'
        log.info(
            'TASK_DONE rates.create_daily_snapshot %s date=%s currencies=%d anomalies=%d',
            action, today, source_count, anomaly_count,
        )
        return {
            'success':      True,
            'action':       action,
            'date':         str(today),
            'currencies':   source_count,
            'anomalies':    anomaly_count,
            'status':       status,
        }

    except Exception as exc:
        delay = _RETRY_BACKOFF[min(self.request.retries, 1)]
        log.error('TASK_ERROR rates.create_daily_snapshot error=%s', exc)
        raise self.retry(exc=exc, countdown=delay)


# ------------------------------------------------------------------ #
#  Auto Profit Mode — optimización de tasas                           #
# ------------------------------------------------------------------ #

@shared_task(
    bind=True,
    acks_late=True,
    max_retries=2,
    name='rates.run_profit_optimizer',
)
def run_profit_optimizer_task(self):
    """
    Ejecuta el optimizador de profit para todas las divisas activas y
    emite las tasas óptimas vía WebSocket para que los operadores las
    apliquen o las descarten.

    NO aplica las tasas automáticamente — solo sugiere y notifica.
    """
    from .profit_optimizer import ProfitOptimizer

    log.info('TASK_START rates.run_profit_optimizer')
    try:
        optimizer = ProfitOptimizer()
        results   = optimizer.optimize_all(include_variants=True)

        payload = {r.currency_code if r.variant is None else r.variant: r.to_dict()
                   for r in results.values()}

        # Notificar via WebSocket
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            layer = get_channel_layer()
            if layer:
                async_to_sync(layer.group_send)('rates_updates', {
                    'type':          'profit_optimizer_update',
                    'optimized_rates': payload,
                    'currency_count': len(payload),
                })
        except Exception as ws_exc:
            log.debug('PROFIT_OPTIMIZER_WS_SKIP %s', ws_exc)

        log.info('TASK_DONE rates.run_profit_optimizer currencies=%d', len(payload))
        return {'success': True, 'optimized': len(payload), 'results': payload}

    except Exception as exc:
        delay = _RETRY_BACKOFF[min(self.request.retries, 1)]
        log.error('TASK_ERROR rates.run_profit_optimizer error=%s', exc)
        raise self.retry(exc=exc, countdown=delay)


# ------------------------------------------------------------------ #
#  Variantes de efectivo                                               #
# ------------------------------------------------------------------ #

@shared_task(
    bind=True,
    acks_late=True,
    max_retries=2,
    name='rates.update_cash_variants',
)
def update_cash_variants_task(self):
    """
    Recalcula y persiste tasas para USD_CASH_LOOSE, USD_SMALL_BILLS y PEN_COINS.
    Programar después de la actualización principal de tasas.
    """
    from .cash_variants import CashVariantService

    log.info('TASK_START rates.update_cash_variants')
    try:
        service = CashVariantService()
        rates   = service.calculate_all()
        saved   = service.save_to_db(rates)

        # Notificar variantes via WebSocket
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            layer = get_channel_layer()
            if layer:
                async_to_sync(layer.group_send)('rates_updates', {
                    'type':          'cash_variants_update',
                    'variants':      {code: r.to_dict() for code, r in rates.items()},
                    'variant_count': saved,
                })
        except Exception as ws_exc:
            log.debug('CASH_VARIANTS_WS_SKIP %s', ws_exc)

        log.info('TASK_DONE rates.update_cash_variants saved=%d', saved)
        return {'success': True, 'saved': saved, 'variants': list(rates.keys())}

    except Exception as exc:
        delay = _RETRY_BACKOFF[min(self.request.retries, 1)]
        log.error('TASK_ERROR rates.update_cash_variants error=%s', exc)
        raise self.retry(exc=exc, countdown=delay)


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


# ─────────────────────────────────────────────────────────────────────────────
#  Capa integrations/ — fetch_all_rates, calculate_consensus, cleanup_old_rates
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    acks_late=True,
    max_retries=2,
    name='rates.fetch_all_rates',
)
def fetch_all_rates_task(self):
    """
    Consulta TODAS las fuentes activas en paralelo (Celery group),
    persiste cada NormalizedRate en ExchangeRateRaw y calcula el consenso.
    Programar cada 5 minutos en Celery Beat.
    """
    from celery import group as celery_group
    log.info('TASK_START rates.fetch_all_rates')
    try:
        from .integrations.registry import get_active_fetchers
        from .integrations.consensus import calculate_consensus
        from .models import ExchangeRateRaw, ExchangeRateSource

        fetchers = get_active_fetchers()
        all_rates = []

        # Prefetch de fuentes UNA vez (evita el N+1: antes se hacía un
        # ExchangeRateSource.objects.get() por cada tasa).
        source_map = {s.id_fuente: s for s in ExchangeRateSource.objects.all()}

        # Ejecutar fetchers secuencialmente (group() requiere que las tareas
        # sean compartidas — aquí las ejecutamos inline para simplicidad)
        raw_objs = []
        for fetcher in fetchers:
            rates = fetcher.fetch_safe()
            for nr in rates:
                try:
                    raw_objs.append(ExchangeRateRaw(
                        fuente = source_map.get(nr.fuente),
                        **nr.to_db(),
                    ))
                    if nr.es_valido:
                        all_rates.append(nr)
                except Exception as exc:
                    log.warning('FETCH_ALL_SAVE_ERROR fuente=%s error=%s', nr.fuente, exc)

        # Una sola inserción por lote (antes: un create() por tasa).
        if raw_objs:
            ExchangeRateRaw.objects.bulk_create(raw_objs, batch_size=500, ignore_conflicts=True)
        saved = len(raw_objs)

        # Calcular consenso a partir de los datos recién guardados
        consensus = calculate_consensus()

        # Publicar via WebSocket
        _broadcast_consensus(consensus)

        log.info('TASK_DONE rates.fetch_all_rates saved=%d consensus_pairs=%d',
                 saved, len(consensus))
        return {'success': True, 'saved': saved, 'consensus_pairs': len(consensus)}

    except Exception as exc:
        delay = _RETRY_BACKOFF[min(self.request.retries, 1)]
        log.error('TASK_ERROR rates.fetch_all_rates error=%s', exc, exc_info=True)
        raise self.retry(exc=exc, countdown=delay)


@shared_task(
    bind=True,
    acks_late=True,
    max_retries=1,
    name='rates.calculate_consensus',
)
def calculate_consensus_task(self, pairs: list | None = None):
    """
    Calcula el consenso ponderado para todos los pares (o los indicados).
    Puede llamarse de forma independiente después de fetch_all_rates.
    """
    log.info('TASK_START rates.calculate_consensus pairs=%s', pairs)
    try:
        from .integrations.consensus import calculate_consensus
        consensus = calculate_consensus(pairs=pairs)
        _broadcast_consensus(consensus)
        log.info('TASK_DONE rates.calculate_consensus pairs=%d', len(consensus))
        return {'success': True, 'pairs': len(consensus), 'result': consensus}
    except Exception as exc:
        log.error('TASK_ERROR rates.calculate_consensus error=%s', exc)
        raise self.retry(exc=exc, countdown=60)


@shared_task(
    bind=True,
    acks_late=True,
    max_retries=1,
    name='rates.cleanup_old_rates',
)
def cleanup_old_rates_task(self):
    """
    Archiva en S3 los ExchangeRateRaw y RawRateSnapshot con más de 90 días.
    NO borra — comprime y mueve. Los datos históricos son activo de ML.
    Programar diariamente a las 3am.
    """
    import datetime, json, gzip
    from django.conf import settings as _settings
    log.info('TASK_START rates.cleanup_old_rates')
    try:
        from .models import ExchangeRateRaw, RawRateSnapshot
        cutoff = __import__('django.utils', fromlist=['timezone']).timezone.now() - \
                 datetime.timedelta(days=90)

        # (queryset, campo de fecha, prefijo de key en S3) por modelo a archivar.
        # RawRateSnapshot (~20k filas/día, poblado por continuous_fx_extraction)
        # antes no se podaba y crecía sin límite.
        targets = [
            (ExchangeRateRaw.objects.filter(timestamp_captura__lt=cutoff), 'raw'),
            (RawRateSnapshot.objects.filter(fetched_at__lt=cutoff),        'snapshots'),
        ]

        total    = 0
        archived  = 0

        s3     = None
        bucket = None
        try:
            import boto3
            s3     = boto3.client('s3')
            bucket = getattr(_settings, 'AWS_STORAGE_BUCKET_NAME', None)
        except Exception as s3_exc:
            log.warning('CLEANUP_S3_SKIP error=%s — datos NO eliminados', s3_exc)

        from io import BytesIO
        for old_qs, prefix in targets:
            count  = old_qs.count()
            total += count
            if count == 0:
                continue

            # Intentar subir a S3 si boto3 y bucket disponibles
            if s3 is not None and bucket:
                try:
                    batch_size = 500
                    offset     = 0
                    while offset < count:
                        batch = list(old_qs.values()[offset:offset + batch_size])
                        key   = (f"rates_archive/"
                                 f"{cutoff.strftime('%Y-%m')}/"
                                 f"{prefix}_{offset}_{offset + len(batch)}.json.gz")
                        buf = BytesIO()
                        with gzip.GzipFile(fileobj=buf, mode='wb') as gz:
                            gz.write(json.dumps(batch, default=str).encode())
                        buf.seek(0)
                        s3.put_object(Bucket=bucket, Key=key, Body=buf.read(),
                                      ContentType='application/gzip')
                        archived += len(batch)
                        offset   += batch_size
                        log.info('CLEANUP_ARCHIVED model=%s batch=%d key=%s',
                                 prefix, len(batch), key)
                except Exception as s3_exc:
                    log.warning('CLEANUP_S3_SKIP model=%s error=%s — datos NO eliminados',
                                prefix, s3_exc)

        if total == 0:
            log.info('TASK_DONE rates.cleanup_old_rates — nothing to archive')
            return {'archived': 0}

        log.info('TASK_DONE rates.cleanup_old_rates total=%d archived=%d', total, archived)
        return {'total': total, 'archived': archived}

    except Exception as exc:
        log.error('TASK_ERROR rates.cleanup_old_rates error=%s', exc)
        raise self.retry(exc=exc, countdown=300)


# ─────────────────────────────────────────────────────────────────────────────
#  Loop continuo de extracción — nunca se detiene
# ─────────────────────────────────────────────────────────────────────────────

# Intervalo entre ciclos (segundos). Redis lock TTL = COUNTDOWN * 2 para evitar
# que dos instancias corran en paralelo ante un reinicio rápido del worker.
_CONTINUOUS_COUNTDOWN = 30
_LOOP_LOCK_KEY        = 'rates:continuous_fx_loop:running'
_LOOP_LOCK_TTL        = _CONTINUOUS_COUNTDOWN * 3   # 90 s — margen generoso

# Fetchers activos en el loop continuo: (nombre_source, clase_fetcher, currency_pair)
_CONTINUOUS_FETCHERS = [
    ('binance_p2p',        'rates.fetchers.binance_p2p.fetch_binance_p2p',       'USDT/BOB'),
    ('dolar_blue_bolivia', 'rates.fetchers.dolar_blue_bolivia.DolarBlueBoliviaFetcher', 'USD/BOB'),
    ('airtm',              'rates.fetchers.airtm_v2_fetcher.AirtmV2Fetcher',     'USD/BOB'),
    ('eldorado',           'rates.fetchers.eldorado_fetcher.EldoradoFetcher',    'USDT/BOB'),
    ('wallbit',            'rates.fetchers.wallbit_fetcher.WallbitFetcher',      'USDT/BOB'),
    ('saldoar',            'rates.fetchers.saldoar_fetcher.SaldoARFetcher',      'USDT/ARS'),
    ('p2p_exchanges',      'rates.fetchers.p2p_exchanges.P2PExchangesFetcher',   'USDT/BOB'),
]


def _import_fetcher(dotpath: str):
    """Importa un fetcher por su ruta de módulo con punto."""
    parts  = dotpath.rsplit('.', 1)
    module = __import__(parts[0], fromlist=[parts[1]])
    return getattr(module, parts[1])


@shared_task(
    bind=True,
    acks_late=True,
    max_retries=None,           # loop perpetuo — nunca agota reintentos
    name='rates.continuous_fx_extraction',
    queue='critical',
    ignore_result=True,
)
def continuous_fx_extraction(self):
    """
    Loop perpetuo de extracción de tasas.

    Al terminar se re-encola a sí mismo con countdown=30 s.
    Si un fetcher individual falla, el error se registra y el ciclo continúa
    con los demás fetchers sin interrumpir el loop.

    Usa un Redis lock distribuido para evitar ejecuciones concurrentes si el
    worker se reinicia mientras una instancia ya está corriendo.
    """
    import time
    from django.core.cache import cache
    from django.utils import timezone
    from .models import RawRateSnapshot

    log.info('CONTINUOUS_FX start cycle=%s', self.request.id)

    # ── Distributed lock ─────────────────────────────────────────────────────
    if not cache.add(_LOOP_LOCK_KEY, self.request.id or 'running', _LOOP_LOCK_TTL):
        log.info('CONTINUOUS_FX already_running — re-schedule in %ds', _CONTINUOUS_COUNTDOWN)
        continuous_fx_extraction.apply_async(countdown=_CONTINUOUS_COUNTDOWN)
        return

    snapshots_created = 0
    try:
        for source_name, fetcher_path, currency_pair in _CONTINUOUS_FETCHERS:
            t0  = time.monotonic()
            ok  = False
            val = None
            err = None

            try:
                fetcher_obj = _import_fetcher(fetcher_path)

                # Soporte para dos patrones: función directa o clase con .fetch()
                if callable(fetcher_obj) and not isinstance(fetcher_obj, type):
                    # función directa (ej. fetch_binance_p2p)
                    result = fetcher_obj()
                    if isinstance(result, dict):
                        val = result.get('mid') or result.get('sell') or result.get('buy')
                    elif hasattr(result, '__iter__'):
                        first = next(iter(result), None)
                        val   = getattr(first, 'mid_rate', None) if first else None
                else:
                    # clase con .fetch()
                    results = fetcher_obj().fetch()
                    first   = results[0] if results else None
                    val     = first.mid_rate if first else None

                if val is not None:
                    ok = True
                    # Actualizar caché Redis con el nuevo valor
                    cache_key = f'rate:{source_name}:{currency_pair}'
                    cache.set(cache_key, str(val), timeout=_CONTINUOUS_COUNTDOWN * 4)

            except Exception as fetch_exc:
                err = str(fetch_exc)
                log.warning(
                    'CONTINUOUS_FX_FETCHER_ERROR source=%s pair=%s error=%s',
                    source_name, currency_pair, fetch_exc,
                )

            elapsed_ms = int((time.monotonic() - t0) * 1000)

            # Persistir snapshot crudo
            try:
                RawRateSnapshot.objects.create(
                    source           = source_name,
                    currency_pair    = currency_pair,
                    raw_value        = val,
                    response_time_ms = elapsed_ms,
                    success          = ok,
                    error_message    = err,
                )
                snapshots_created += 1
            except Exception as db_exc:
                log.error('CONTINUOUS_FX_DB_ERROR source=%s error=%s', source_name, db_exc)

            log.debug(
                'CONTINUOUS_FX_TICK source=%s pair=%s ok=%s val=%s ms=%d',
                source_name, currency_pair, ok, val, elapsed_ms,
            )

    finally:
        cache.delete(_LOOP_LOCK_KEY)

    log.info('CONTINUOUS_FX cycle_done snapshots=%d — re-queuing in %ds',
             snapshots_created, _CONTINUOUS_COUNTDOWN)

    # Auto re-encolarse para el siguiente ciclo
    continuous_fx_extraction.apply_async(countdown=_CONTINUOUS_COUNTDOWN)


def _broadcast_consensus(consensus: dict) -> None:
    """Publica el consenso al group 'rates_live' via Django Channels."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        from django.utils import timezone

        layer = get_channel_layer()
        if layer is None:
            return

        pares_payload = {}
        for par, data in consensus.items():
            cambio = data.get('cambio_pct_24h')
            pares_payload[par] = {
                'consenso':      data.get('consenso'),
                'compra':        data.get('compra'),
                'venta':         data.get('venta'),
                'fuentes':       data.get('fuentes', 0),
                'confianza':     data.get('confianza', 0),
                'cambio_pct':    float(cambio) if cambio else 0.0,
                'tendencia':     data.get('tendencia', 'NEUTRAL'),
            }

        async_to_sync(layer.group_send)('rates_live', {
            'type':      'rates_update',
            'timestamp': timezone.now().isoformat(),
            'pares':     pares_payload,
        })
        log.debug('WS_BROADCAST_CONSENSUS pairs=%d', len(consensus))
    except Exception as exc:
        log.debug('WS_BROADCAST_CONSENSUS_SKIP error=%s', exc)
