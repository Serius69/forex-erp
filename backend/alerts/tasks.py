"""
Tareas Celery de alertas.

`evaluate_all_alerts` — barrido CONSOLIDADO del motor de alertas.

Contexto (auditoría #27 — fan-out O(sucursales × divisas)):
    Hasta ahora ~7 tasks de tasas (`fetch_parallel_rate`, `update_digital_rates`,
    `update_parallel_rates`, `update_all_rates`, `run_fx_engine_task`,
    `fetch_binance_p2p_task`, `fetch_dolar_blue_bolivia_task`) ejecutaban, cada una
    de forma SÍNCRONA y con un subconjunto DISTINTO de divisas, el mismo doble bucle
    `for branch in activas: for code in currencies: AlertGenerator.generar_alertas(...)`.
    Como esas tasks se disparan casi simultáneamente (cada 5-60 min), el motor de
    alertas se barría decenas de veces por hora de forma redundante.

    Esta tarea hace EXACTAMENTE el mismo trabajo que hacían las 7 juntas —
    `AlertGenerator.generar_alertas(branch, currency)` por cada par sucursal×divisa —
    pero UNA sola vez por ciclo y cubriendo la UNIÓN de TODAS las divisas activas.
    Al cubrir la unión (no un subconjunto), el debounce de los call-sites NO puede
    "perder" ninguna divisa: cualquier divisa que alguna task individual evaluaba hoy
    está incluida aquí.

Seguridad de correctitud:
    - El universo de divisas = divisas activas (`Currency.is_active=True`) ∪ divisas
      con una `ExchangeRate` vigente (`valid_until IS NULL`), excluyendo siempre BOB.
      Ese conjunto es un SUPERCONJUNTO de cualquier lista `currencies` que pasaba
      cualquiera de las 7 tasks (cada task pasaba las divisas que acababa de escribir,
      que por definición tienen una tasa vigente) → no se pierde ningún (sucursal×divisa).
    - `generar_alertas` es idempotente: cada (tipo, alert_type, branch, currency) se
      deduplica 30 min en caché (`AlertGenerator.DEDUP_MINUTES`), así que ejecutarlo de
      más no duplica alertas. Sus 4 evaluadores solo LEEN la BD → correr en un job aparte
      es seguro.
"""
from __future__ import annotations

import logging

from celery import shared_task

log = logging.getLogger('kapitalya.alerts.tasks')


def _union_de_divisas_activas() -> list[str]:
    """
    Devuelve la UNIÓN de códigos de divisa que hoy podrían generar alertas:
    activas (`Currency.is_active=True`) ∪ con `ExchangeRate` vigente, sin BOB.
    """
    from rates.models import Currency, ExchangeRate

    codes: set[str] = set(
        Currency.objects
        .filter(is_active=True)
        .exclude(code='BOB')
        .values_list('code', flat=True)
    )
    # Cualquier divisa con tasa vigente que alguna task de tasas pudiera pasar,
    # aunque su Currency estuviera (transitoriamente) inactiva.
    codes |= set(
        ExchangeRate.objects
        .filter(valid_until__isnull=True)
        .exclude(currency_from__code='BOB')
        .values_list('currency_from__code', flat=True)
    )
    return sorted(codes)


@shared_task(
    bind=True,
    acks_late=True,
    max_retries=0,
    soft_time_limit=180,
    time_limit=240,
    name='alerts.evaluate_all',
)
def evaluate_all_alerts(self):
    """
    Barrido único del motor de alertas para TODAS las sucursales activas × la UNIÓN
    de todas las divisas activas. Reemplaza el fan-out redundante embebido en las
    tasks de tasas (ver módulo docstring).

    Fire-and-forget por par: un fallo evaluando una (sucursal, divisa) se registra y
    no interrumpe el resto — mismo contrato que el `_run_alert_generator_for_branches`
    original.
    """
    from alerts.services import AlertGenerator
    from users.models import Branch

    branches   = list(Branch.objects.filter(is_active=True))
    currencies = _union_de_divisas_activas()

    evaluated = 0
    for branch in branches:
        for code in currencies:
            try:
                AlertGenerator.generar_alertas(branch, currency=code)
                evaluated += 1
            except Exception as exc:
                log.debug('EVALUATE_ALL_SKIP branch=%s currency=%s err=%s',
                          branch, code, exc)

    log.info(
        'TASK_DONE alerts.evaluate_all branches=%d currencies=%d pairs=%d',
        len(branches), len(currencies), evaluated,
    )
    return {
        'branches':   len(branches),
        'currencies': currencies,
        'pairs':      evaluated,
    }
