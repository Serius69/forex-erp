"""
Tests del barrido consolidado de alertas (auditoría #27 — fan-out).

Cubren:
  1. `evaluate_all_alerts` evalúa la UNIÓN de divisas activas × cada sucursal activa,
     exactamente una vez por par (no se pierde ninguna sucursal×divisa; BOB excluida).
  2. El debounce de `_run_alert_generator_for_branches` encola el barrido a lo sumo una
     vez por ventana, aunque las ~7 tasks de tasas lo llamen casi simultáneamente.
"""
from unittest.mock import patch

import pytest
from django.core.cache import cache

from rates.models import Currency
from users.models import Branch


@pytest.fixture
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


def _mk_branch(name, code, active=True):
    return Branch.objects.create(
        name=name, code=code, address='x', phone='0', is_active=active,
    )


def _mk_currency(code, active=True):
    return Currency.objects.create(
        code=code, name_en=code, name_es=code, symbol=code, is_active=active,
    )


@pytest.mark.django_db
def test_evaluate_all_cubre_union_divisas_activas_por_sucursal(_clean_cache):
    """Cada sucursal activa se evalúa contra cada divisa activa (≠BOB), una sola vez.

    Robusto ante las divisas/sucursales que las data-migrations ya siembran en la BD de
    test: el conjunto esperado se deriva independientemente de la BD, no se hardcodea.
    """
    from alerts.tasks import evaluate_all_alerts

    b1 = _mk_branch('Central', 'C1')
    b2 = _mk_branch('Sur', 'C2')
    b_off = _mk_branch('Vieja', 'C3', active=False)   # inactiva → no debe evaluarse

    _mk_currency('QQQ')                               # divisa activa nueva → debe incluirse
    _mk_currency('JPY', active=False)                 # inactiva y sin tasa → excluida

    # Universo esperado, calculado de forma INDEPENDIENTE de la implementación:
    #   divisas activas (≠BOB) × sucursales activas.
    active_codes = set(
        Currency.objects.filter(is_active=True)
        .exclude(code='BOB').values_list('code', flat=True)
    )
    active_branches = list(Branch.objects.filter(is_active=True).values_list('code', flat=True))
    esperado = {(bc, c) for bc in active_branches for c in active_codes}

    calls = []
    with patch(
        'alerts.services.AlertGenerator.generar_alertas',
        side_effect=lambda branch, currency=None, **kw: calls.append((branch.code, currency)) or [],
    ):
        result = evaluate_all_alerts.apply().get()

    assert set(calls) == esperado                     # cubre TODA la unión, ni de más ni de menos
    assert len(calls) == len(esperado)                # exactamente una vez por (sucursal, divisa)
    # Aserciones puntuales de correctitud:
    assert ('C1', 'QQQ') in calls and ('C2', 'QQQ') in calls   # divisa activa nueva cubierta
    assert all(c != 'BOB' for _, c in calls)                   # BOB nunca se evalúa
    assert all(bc != b_off.code for bc, _ in calls)            # sucursal inactiva excluida
    assert all(c != 'JPY' for _, c in calls)                   # divisa inactiva sin tasa excluida
    assert 'BOB' not in result['currencies']
    assert 'QQQ' in result['currencies']


@pytest.mark.django_db
def test_debounce_encola_una_sola_vez_por_ventana(_clean_cache):
    """Siete llamadas casi-simultáneas → una sola `evaluate_all_alerts.delay()`."""
    from rates.tasks import _run_alert_generator_for_branches, _ALERT_DEBOUNCE_KEY

    with patch('alerts.tasks.evaluate_all_alerts.delay') as mock_delay:
        for currencies in (['USD'], ['USDT'], ['EUR'], ['USD'], ['BRL'], ['ARS'], ['PEN']):
            _run_alert_generator_for_branches(currencies)
        assert mock_delay.call_count == 1             # debounced dentro de la ventana

        # Expira la ventana → el siguiente disparo vuelve a encolar.
        cache.delete(_ALERT_DEBOUNCE_KEY)
        _run_alert_generator_for_branches(['USD'])
        assert mock_delay.call_count == 2
