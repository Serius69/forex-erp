# capital/tests/test_services.py
"""
Tests unitarios para capital/services.py.

Cubre:
  - CapitalService.calcular_capital: valoración de divisas a tasa de venta,
    normalización por scale_factor, fallback de mercado, composición de
    efectivo/digital/pasivos, filtro por sucursal y advertencias.
  - GananciaService.ganancia_por_divisa / resumen_financiero: cálculo de
    ganancia con spreads reales, filtros por sucursal/divisa y gastos.
  - CashBOBService: get_or_create_today, upsert (+ sync a CapitalComposicion)
    y deducir_bob con prioridad de denominaciones e InsufficientCashError.

Nota: las transacciones de prueba se crean con bulk_create para NO disparar
las señales post_save (apply_transaction_effects) — GananciaService solo
necesita las filas en DB, no los efectos de caja.
"""
from decimal import Decimal

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from capital.services import (
    CapitalService, GananciaService, CashBOBService, InsufficientCashError,
)

User = get_user_model()


# ── Helpers para crear fixtures mínimas ───────────────────────────────────────

def _make_company(name='TestCo'):
    from tenants.models import Company
    return Company.objects.create(name=name, is_active=True)


def _make_branch(company, code='SUC01', name='Sucursal Test'):
    from users.models import Branch
    return Branch.objects.create(company=company, code=code, name=name, is_active=True)


def _make_user(company, branch, role='ADMIN', username=None):
    username = username or f'user_{role.lower()}_{branch.code}'
    user = User.objects.create_user(
        username=username, password='testpass123',
        email=f'{username}@test.com',
    )
    user.company   = company
    user.branch    = branch
    user.role      = role
    user.is_active = True
    user.save()
    return user


def _make_currency(code='USD', scale_factor=1):
    from rates.models import Currency
    cur, _ = Currency.objects.get_or_create(
        code=code,
        defaults={
            'name_en': code, 'name_es': code,
            'symbol': code, 'is_active': True,
            'use_exchange_rate': True, 'is_base_currency': (code == 'BOB'),
            'scale_factor': scale_factor,
        },
    )
    return cur


def _make_exchange_rate(currency_from, currency_to, buy=6.85, sell=6.95,
                        market_type='parallel'):
    from rates.models import ExchangeRate
    return ExchangeRate.objects.create(
        currency_from=currency_from,
        currency_to=currency_to,
        market_type=market_type,
        official_rate=Decimal(str(sell)),
        buy_rate=Decimal(str(buy)),
        sell_rate=Decimal(str(sell)),
        avg_rate=Decimal(str((buy + sell) / 2)),
        valid_from=timezone.now(),
        source='TEST',
        source_method='MANUAL',
    )


def _make_inventory(currency, branch, physical='0', digital='0'):
    from inventory.models import CurrencyInventory
    return CurrencyInventory.objects.create(
        currency=currency, branch=branch,
        physical_balance=Decimal(physical),
        digital_balance=Decimal(digital),
    )


def _make_composicion(branch, user, **kwargs):
    from capital.models import CapitalComposicion
    return CapitalComposicion.objects.create(
        branch=branch, registrado_por=user, **kwargs,
    )


class CapitalTestBase(TestCase):
    """Fixtures comunes: empresa, sucursal, usuario admin, BOB/USD y tasa paralela."""

    def setUp(self):
        self.company = _make_company('CasaCambioTest')
        self.branch  = _make_branch(self.company, 'A001', 'Sucursal Central')
        self.admin   = _make_user(self.company, self.branch, 'ADMIN', 'admin_capital')
        self.bob     = _make_currency('BOB')
        self.usd     = _make_currency('USD')
        self.rate_usd = _make_exchange_rate(self.usd, self.bob, buy=6.85, sell=6.95)


# ── CapitalService.calcular_capital ───────────────────────────────────────────

class CapitalServiceTests(CapitalTestBase):

    def test_capital_vacio_retorna_ceros(self):
        """Sin inventario ni composición, el capital neto es 0.00."""
        resultado = CapitalService.calcular_capital()
        self.assertEqual(resultado['capital_neto'], '0.00')
        self.assertEqual(resultado['total_activos'], '0.00')
        self.assertEqual(resultado['total_pasivos'], '0.00')
        self.assertEqual(resultado['divisas'], {})
        self.assertEqual(resultado['totales']['divisas_bob'], '0.00')

    def test_divisas_valoradas_a_tasa_de_venta(self):
        """El stock de divisa se valora al sell_rate del mercado 'parallel'."""
        _make_inventory(self.usd, self.branch, physical='1000')
        resultado = CapitalService.calcular_capital()

        self.assertIn('USD', resultado['divisas'])
        usd = resultado['divisas']['USD']
        self.assertEqual(usd['stock'], '1000.00')
        self.assertEqual(usd['tc_venta_unit'], '6.9500')
        # 1000 × 6.95 = 6950.00
        self.assertEqual(usd['valor_bob'], '6950.00')
        self.assertEqual(resultado['totales']['divisas_bob'], '6950.00')
        self.assertEqual(resultado['capital_neto'], '6950.00')

    def test_scale_factor_normaliza_tasa_por_lote(self):
        """Con scale_factor=1000 la tasa cotizada es por 1000 unidades."""
        ars = _make_currency('ARS', scale_factor=1000)
        _make_exchange_rate(ars, self.bob, buy=4.50, sell=5.00)
        _make_inventory(ars, self.branch, physical='10000')

        resultado = CapitalService.calcular_capital()
        info = resultado['divisas']['ARS']
        # tc unitario = 5.00 / 1000 = 0.0050 → 10000 × 0.005 = 50.00 BOB
        self.assertEqual(info['tc_venta_unit'], '0.0050')
        self.assertEqual(info['valor_bob'], '50.00')

    def test_divisa_sin_tasa_activa_genera_advertencia(self):
        """Inventario sin tasa activa se excluye y produce una advertencia."""
        eur = _make_currency('EUR')
        _make_inventory(eur, self.branch, physical='500')

        resultado = CapitalService.calcular_capital()
        self.assertNotIn('EUR', resultado['divisas'])
        self.assertTrue(
            any('EUR' in adv for adv in resultado['advertencias']),
            f"Se esperaba advertencia sobre EUR: {resultado['advertencias']}",
        )

    def test_fallback_a_paralelo_fisico_empresa(self):
        """Sin tasa 'parallel', usa la de mercado 'paralelo_fisico_empresa'."""
        eur = _make_currency('EUR')
        _make_exchange_rate(eur, self.bob, buy=7.50, sell=7.80,
                            market_type='paralelo_fisico_empresa')
        _make_inventory(eur, self.branch, physical='100')

        resultado = CapitalService.calcular_capital()
        info = resultado['divisas']['EUR']
        self.assertEqual(info['market_type'], 'paralelo_fisico_empresa')
        self.assertEqual(info['valor_bob'], '780.00')

    def test_stock_cero_se_excluye_del_desglose(self):
        """Inventarios con stock 0 no aparecen en el desglose de divisas."""
        _make_inventory(self.usd, self.branch, physical='0')
        resultado = CapitalService.calcular_capital()
        self.assertEqual(resultado['divisas'], {})

    def test_composicion_suma_efectivo_digital_y_pasivos(self):
        """CAPITAL NETO = efectivo + digital - pasivos (sin divisas)."""
        _make_composicion(
            self.branch, self.admin,
            fuertes=Decimal('1000'), caja_chica=Decimal('200'),
            monedas=Decimal('50'), rotos=Decimal('10'), sueltos=Decimal('40'),
            qr_transferencias=Decimal('500'),
            tarjetas_telefonicas=Decimal('100'),
            pasivos=Decimal('300'),
        )
        resultado = CapitalService.calcular_capital(branch=self.branch)

        self.assertEqual(resultado['efectivo']['total'], '1300.00')
        self.assertEqual(resultado['digital']['total'], '600.00')
        self.assertEqual(resultado['total_pasivos'], '300.00')
        # 1300 + 600 - 300 = 1600
        self.assertEqual(resultado['total_activos'], '1900.00')
        self.assertEqual(resultado['capital_neto'], '1600.00')

    def test_filtro_por_sucursal(self):
        """branch=X solo considera inventario y composición de esa sucursal."""
        branch_b = _make_branch(self.company, 'B001', 'Sucursal Norte')
        _make_inventory(self.usd, self.branch, physical='100')
        _make_inventory(self.usd, branch_b, physical='900')
        _make_composicion(branch_b, self.admin, fuertes=Decimal('5000'))

        solo_a = CapitalService.calcular_capital(branch=self.branch)
        self.assertEqual(solo_a['divisas']['USD']['stock'], '100.00')
        self.assertEqual(solo_a['efectivo']['total'], '0.00')

        # Sin filtro: agrega el stock de ambas sucursales bajo el mismo código
        todas = CapitalService.calcular_capital()
        self.assertEqual(todas['divisas']['USD']['stock'], '1000.00')
        self.assertEqual(todas['divisas']['USD']['valor_bob'], '6950.00')
        self.assertEqual(todas['efectivo']['total'], '5000.00')

    def test_sin_divisa_bob_genera_advertencia(self):
        """Si BOB no existe en DB, retorna advertencia sin romper."""
        # Borrar BOB elimina en cascada la tasa USD→BOB
        self.bob.delete()
        resultado = CapitalService.calcular_capital()
        self.assertIn('Divisa BOB no encontrada en DB', resultado['advertencias'])


# ── GananciaService ───────────────────────────────────────────────────────────

class GananciaServiceTests(CapitalTestBase):

    def setUp(self):
        super().setUp()
        self.cashier = _make_user(self.company, self.branch, 'CASHIER', 'cashier_gan')
        self.hoy = timezone.localdate()
        self._tx_seq = 0

    def _make_tx(self, tx_type, currency_from, currency_to,
                 amount_from, amount_to, branch=None, status='COMPLETED'):
        """
        Crea una Transaction vía bulk_create para NO disparar señales post_save
        (apply_transaction_effects tocaría CapitalComposicion / CashFlowLog).
        """
        from transactions.models import Transaction
        self._tx_seq += 1
        tx = Transaction(
            transaction_number=f'TEST{self._tx_seq:08d}',
            transaction_type=tx_type,
            transaction_category='INTERNA',
            currency_from=currency_from,
            currency_to=currency_to,
            amount_from=amount_from,
            amount_to=amount_to,
            exchange_rate=Decimal('6.90'),
            payment_method='CASH',
            cashier=self.cashier,
            branch=branch or self.branch,
            status=status,
        )
        Transaction.objects.bulk_create([tx])
        return tx

    def test_ganancia_compra_venta_usd(self):
        """BUY 100 USD por 685 Bs y SELL 100 USD por 700 Bs → ganancia 15 Bs."""
        self._make_tx('BUY', self.usd, self.bob, 100, 685)   # casa compra USD
        self._make_tx('SELL', self.bob, self.usd, 700, 100)  # casa vende USD

        resultado = GananciaService.ganancia_por_divisa(self.hoy, self.hoy)
        self.assertEqual(len(resultado), 1)
        g = resultado[0]
        self.assertEqual(g['divisa'], 'USD')
        self.assertEqual(g['ops_compra'], 1)
        self.assertEqual(g['ops_venta'], 1)
        self.assertEqual(g['unidades_compradas'], '100.00')
        self.assertEqual(g['unidades_vendidas'], '100.00')
        self.assertEqual(g['costo_bob'], '685.00')
        self.assertEqual(g['ingreso_bob'], '700.00')
        self.assertEqual(g['ganancia_bob'], '15.00')
        self.assertEqual(g['tc_compra_prom'], '6.8500')
        self.assertEqual(g['tc_venta_prom'], '7.0000')
        self.assertEqual(g['spread_prom'], '0.1500')
        # 15 / 685 × 100 = 2.19 %
        self.assertEqual(g['margen_pct'], '2.19')

    def test_ignora_transacciones_no_completadas(self):
        """Solo status='COMPLETED' entra al cálculo de ganancia."""
        self._make_tx('BUY', self.usd, self.bob, 100, 685, status='PENDING')
        self._make_tx('BUY', self.usd, self.bob, 200, 1370, status='CANCELLED')
        resultado = GananciaService.ganancia_por_divisa(self.hoy, self.hoy)
        self.assertEqual(resultado, [])

    def test_rango_sin_transacciones_retorna_lista_vacia(self):
        """Un rango de fechas sin operaciones retorna []."""
        resultado = GananciaService.ganancia_por_divisa(self.hoy, self.hoy)
        self.assertEqual(resultado, [])

    def test_filtro_por_sucursal(self):
        """branch=X excluye las transacciones de otras sucursales."""
        branch_b  = _make_branch(self.company, 'B001', 'Sucursal Norte')
        cashier_b = _make_user(self.company, branch_b, 'CASHIER', 'cashier_b_gan')
        self._make_tx('BUY', self.usd, self.bob, 100, 685)
        self._make_tx('BUY', self.usd, self.bob, 300, 2055, branch=branch_b)

        resultado = GananciaService.ganancia_por_divisa(
            self.hoy, self.hoy, branch=self.branch,
        )
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]['unidades_compradas'], '100.00')
        self.assertEqual(resultado[0]['costo_bob'], '685.00')

    def test_filtro_por_codigo_divisa(self):
        """currency_code limita el resultado a esa divisa."""
        eur = _make_currency('EUR')
        self._make_tx('BUY', self.usd, self.bob, 100, 685)
        self._make_tx('BUY', eur, self.bob, 50, 390)

        resultado = GananciaService.ganancia_por_divisa(
            self.hoy, self.hoy, currency_code='EUR',
        )
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]['divisa'], 'EUR')

    def test_ordena_por_ganancia_descendente(self):
        """El resultado viene ordenado por ganancia_bob de mayor a menor."""
        eur = _make_currency('EUR')
        # USD: gana 15 Bs
        self._make_tx('BUY', self.usd, self.bob, 100, 685)
        self._make_tx('SELL', self.bob, self.usd, 700, 100)
        # EUR: gana 100 Bs
        self._make_tx('BUY', eur, self.bob, 100, 700)
        self._make_tx('SELL', self.bob, eur, 800, 100)

        resultado = GananciaService.ganancia_por_divisa(self.hoy, self.hoy)
        self.assertEqual([g['divisa'] for g in resultado], ['EUR', 'USD'])

    def test_resumen_financiero_descuenta_gastos(self):
        """ganancia_neta = ganancia_bruta (divisas + tarjetas) - gastos."""
        from capital.models import Gasto

        self._make_tx('BUY', self.usd, self.bob, 100, 685)
        self._make_tx('SELL', self.bob, self.usd, 700, 100)  # ganancia 15 Bs

        Gasto.objects.create(
            categoria='ALQUILER', descripcion='Alquiler oficina',
            monto_bob=Decimal('100.00'), branch=self.branch,
            registrado_por=self.admin,
        )
        Gasto.objects.create(
            categoria='SERVICIOS', descripcion='Luz y agua',
            monto_bob=Decimal('50.00'), branch=self.branch,
            registrado_por=self.admin,
        )

        resumen = GananciaService.resumen_financiero(self.hoy, self.hoy)
        self.assertEqual(resumen['ganancias_divisas']['total'], '15.00')
        self.assertEqual(resumen['ganancias_tarjetas']['total'], '0.00')
        self.assertEqual(resumen['gastos']['total'], '150.00')
        self.assertEqual(resumen['gastos']['count'], 2)
        self.assertEqual(resumen['ganancia_bruta'], '15.00')
        # 15 - 150 = -135
        self.assertEqual(resumen['ganancia_neta'], '-135.00')
        # Categorías ordenadas por total descendente
        cats = [c['categoria'] for c in resumen['gastos']['por_categoria']]
        self.assertEqual(cats, ['ALQUILER', 'SERVICIOS'])

    def test_resumen_financiero_filtra_gastos_por_sucursal(self):
        """Los gastos de otra sucursal no afectan el resumen filtrado."""
        from capital.models import Gasto
        branch_b = _make_branch(self.company, 'B001', 'Sucursal Norte')
        Gasto.objects.create(
            categoria='OTROS', descripcion='Gasto ajeno',
            monto_bob=Decimal('999.00'), branch=branch_b,
            registrado_por=self.admin,
        )
        resumen = GananciaService.resumen_financiero(
            self.hoy, self.hoy, branch=self.branch,
        )
        self.assertEqual(resumen['gastos']['total'], '0.00')
        self.assertEqual(resumen['ganancia_neta'], '0.00')


# ── CashBOBService ────────────────────────────────────────────────────────────

class CashBOBServiceTests(CapitalTestBase):

    def _make_cash(self, **kwargs):
        from capital.models import CashBOB
        return CashBOB.objects.create(
            branch=self.branch, registrado_por=self.admin, **kwargs,
        )

    # ── get_or_create_today ──────────────────────────────────────────────────

    def test_get_or_create_today_crea_y_reutiliza(self):
        """Primera llamada crea la caja del día; la segunda retorna la misma."""
        from capital.models import CashBOB
        cash1 = CashBOBService.get_or_create_today(self.branch, self.admin)
        cash2 = CashBOBService.get_or_create_today(self.branch, self.admin)

        self.assertEqual(cash1.pk, cash2.pk)
        self.assertEqual(cash1.fecha, timezone.localdate())
        self.assertEqual(cash1.total_efectivo_fisico(), Decimal('0'))
        self.assertEqual(CashBOB.objects.count(), 1)

    # ── upsert ───────────────────────────────────────────────────────────────

    def test_upsert_crea_y_sincroniza_composicion(self):
        """upsert crea la caja y empuja los totales a CapitalComposicion."""
        from capital.models import CapitalComposicion
        cash = CashBOBService.upsert(self.branch, self.admin, {
            'fuertes_100':    10,   # 1000 Bs
            'caja_chica_20':  5,    # 100 Bs
            'sueltos_10':     3,    # 30 Bs
            'qr_transferencias': Decimal('250.50'),
        })

        self.assertEqual(cash.total_fuertes(), Decimal('1000'))
        self.assertEqual(cash.total_caja_chica(), Decimal('100'))
        self.assertEqual(cash.total_sueltos(), Decimal('30'))
        self.assertEqual(cash.total_efectivo_fisico(), Decimal('1130'))
        self.assertEqual(cash.total_general_bob(), Decimal('1380.50'))

        comp = CapitalComposicion.objects.get(
            branch=self.branch, fecha=timezone.localdate(),
        )
        self.assertEqual(comp.fuertes, Decimal('1000'))
        self.assertEqual(comp.caja_chica, Decimal('100'))
        self.assertEqual(comp.sueltos, Decimal('30'))
        self.assertEqual(comp.qr_transferencias, Decimal('250.50'))

    def test_upsert_actualiza_caja_existente(self):
        """Un segundo upsert modifica la fila del día (no crea otra)."""
        from capital.models import CashBOB
        CashBOBService.upsert(self.branch, self.admin, {'fuertes_200': 2})
        cash = CashBOBService.upsert(self.branch, self.admin, {'fuertes_200': 5})

        self.assertEqual(CashBOB.objects.count(), 1)
        self.assertEqual(cash.fuertes_200, 5)
        self.assertEqual(cash.total_fuertes(), Decimal('1000'))

    # ── deducir_bob ──────────────────────────────────────────────────────────

    def test_deducir_bob_prioriza_caja_chica(self):
        """La deducción consume caja_chica antes que sueltos y fuertes."""
        self._make_cash(
            caja_chica_10=5, caja_chica_100=3,   # 50 + 300
            sueltos_20=2,                         # 40
            fuertes_50=4,                         # 200
        )
        resultado = CashBOBService.deducir_bob(self.branch, Decimal('150'))

        self.assertEqual(resultado['deducted_bob'], '150')
        self.assertEqual(resultado['saldo_previo'], '590')
        self.assertEqual(resultado['saldo_nuevo'], '440')
        # 5×10 + 1×100 — solo caja chica
        self.assertEqual([op['campo'] for op in resultado['operations']],
                         ['caja_chica_10', 'caja_chica_100'])

        from capital.models import CashBOB
        cash = CashBOB.objects.get(branch=self.branch)
        self.assertEqual(cash.caja_chica_10, 0)
        self.assertEqual(cash.caja_chica_100, 2)
        self.assertEqual(cash.sueltos_20, 2)     # intactos
        self.assertEqual(cash.fuertes_50, 4)     # intactos

    def test_deducir_bob_cae_en_cascada_a_sueltos_y_fuertes(self):
        """Cuando caja chica no alcanza, sigue con sueltos y luego fuertes."""
        self._make_cash(
            caja_chica_10=2,   # 20
            sueltos_10=1, sueltos_20=1,  # 30
            fuertes_50=2,      # 100
        )
        resultado = CashBOBService.deducir_bob(self.branch, Decimal('100'))

        grupos = [op['grupo'] for op in resultado['operations']]
        self.assertEqual(grupos, ['caja_chica', 'sueltos', 'sueltos', 'fuertes'])
        self.assertEqual(resultado['saldo_nuevo'], '50')

        from capital.models import CashBOB
        cash = CashBOB.objects.get(branch=self.branch)
        self.assertEqual(cash.caja_chica_10, 0)
        self.assertEqual(cash.sueltos_10, 0)
        self.assertEqual(cash.sueltos_20, 0)
        self.assertEqual(cash.fuertes_50, 1)

    def test_deducir_bob_saldo_insuficiente(self):
        """Si el efectivo físico total no cubre el monto, lanza el error."""
        self._make_cash(caja_chica_10=5)  # 50 Bs
        with self.assertRaises(InsufficientCashError) as ctx:
            CashBOBService.deducir_bob(self.branch, Decimal('500'))
        self.assertIn('insuficiente', str(ctx.exception).lower())

    def test_deducir_bob_sin_cambio_exacto(self):
        """Con saldo suficiente pero sin denominaciones para cambio exacto,
        lanza InsufficientCashError y NO modifica la caja en DB."""
        self._make_cash(fuertes_200=1)  # 200 Bs, pero se piden 150
        with self.assertRaises(InsufficientCashError) as ctx:
            CashBOBService.deducir_bob(self.branch, Decimal('150'))
        self.assertIn('cambio exacto', str(ctx.exception))

        from capital.models import CashBOB
        cash = CashBOB.objects.get(branch=self.branch)
        self.assertEqual(cash.fuertes_200, 1)

    def test_deducir_bob_save_false_no_persiste(self):
        """Con save=False el cálculo se retorna pero la DB queda intacta."""
        self._make_cash(caja_chica_10=10)  # 100 Bs
        resultado = CashBOBService.deducir_bob(
            self.branch, Decimal('50'), save=False,
        )
        self.assertEqual(resultado['saldo_nuevo'], '50')

        from capital.models import CashBOB
        cash = CashBOB.objects.get(branch=self.branch)
        self.assertEqual(cash.caja_chica_10, 10)
        self.assertEqual(cash.total_efectivo_fisico(), Decimal('100'))
