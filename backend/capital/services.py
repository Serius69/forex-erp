# capital/services.py
"""
Motor de cálculo de capital — Kapitalya Casa de Cambio Bolivia.

FÓRMULA:
  CAPITAL NETO = TOTAL ACTIVOS - TOTAL PASIVOS

  TOTAL ACTIVOS =
    A) DIVISAS EN EFECTIVO
       Valor = Σ (stock_divisa × tasa_venta_actual)
       Tasa normalizada: si scale_factor=1000, la tasa cotizada es por 1000 unidades
       → valor_bob = stock × (tasa_venta / scale_factor)

    B) EFECTIVO BOB (de CapitalComposicion)
       = fuertes + caja_chica + monedas + rotos + sueltos

    C) DIGITAL
       = qr_transferencias + tarjetas_telefonicas

    D) TARJETAS TELEFÓNICAS (inventario módulo tarjetas)
       = Σ (stock_tipo × precio_venta_prom_ultimas_30_ventas)

  TOTAL PASIVOS = pasivos (de CapitalComposicion)
"""
import logging
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from datetime import date, timedelta

log = logging.getLogger('capital')
MONEY_Q = Decimal('0.01')
RATE_Q  = Decimal('0.0001')


def _q(val, quantum=MONEY_Q) -> Decimal:
    return Decimal(str(val or 0)).quantize(quantum, rounding=ROUND_HALF_UP)




class CapitalService:
    """
    Calcula el capital total en tiempo real.
    No almacena resultados intermedios — usa siempre datos actuales de DB.
    """

    @staticmethod
    def calcular_capital(branch=None) -> dict:
        """
        Retorna estructura completa del capital con desglose.

        Args:
            branch: filtrar por sucursal; None = todas (solo ADMIN).

        Returns:
            {
              capital_neto, total_activos, total_pasivos,
              divisas: { USD: {stock, tc_venta, valor_bob, ...}, ... },
              efectivo: { fuertes, caja_chica, monedas, rotos, sueltos,
                          total_efectivo },
              digital:  { qr_transferencias, tarjetas_telefonicas,
                          total_digital },
              tarjetas_modulo: { NombreTipo: {stock, precio_prom, valor_bob} },
              totales: { divisas_bob, efectivo_bob, digital_bob, tarjetas_bob },
              advertencias: [...],
              calculado_en: ISO datetime,
            }
        """
        from inventory.models import CurrencyInventory
        from rates.models import ExchangeRate, Currency
        from .models import CapitalComposicion

        resultado = {
            'capital_neto':     _q(0),
            'total_activos':    _q(0),
            'total_pasivos':    _q(0),
            'divisas':          {},
            'efectivo':         {
                'fuertes':    _q(0), 'caja_chica':  _q(0),
                'monedas':    _q(0), 'rotos':       _q(0),
                'sueltos':    _q(0), 'total':       _q(0),
            },
            'digital': {
                'qr_transferencias':    _q(0),
                'tarjetas_telefonicas': _q(0),
                'total':                _q(0),
            },
            'tarjetas_modulo':  {},
            'totales': {
                'divisas_bob':   _q(0),
                'efectivo_bob':  _q(0),
                'digital_bob':   _q(0),
                'tarjetas_bob':  _q(0),
            },
            'advertencias':  [],
            'calculado_en':  timezone.now().isoformat(),
        }

        # ── A) DIVISAS × tasa_venta (normalizada por scale_factor) ───────────
        inv_qs = CurrencyInventory.objects.select_related('currency', 'branch')
        if branch:
            inv_qs = inv_qs.filter(branch=branch)

        # Precargar tasas activas en un dict para evitar N+1
        bob = Currency.objects.filter(code='BOB').first()
        if not bob:
            resultado['advertencias'].append('Divisa BOB no encontrada en DB')
            return _serialize_resultado(resultado)

        rates_activas = {}
        for r in (ExchangeRate.objects
                  .filter(currency_to=bob, valid_until__isnull=True,
                          market_type='parallel')
                  .select_related('currency_from')):
            rates_activas[r.currency_from.id] = r

        # Fallback a paralelo_fisico_empresa si no hay parallel
        rates_fallback = {}
        for r in (ExchangeRate.objects
                  .filter(currency_to=bob, valid_until__isnull=True,
                          market_type='paralelo_fisico_empresa')
                  .select_related('currency_from')):
            rates_fallback[r.currency_from.id] = r

        total_divisas = _q(0)
        for inv in inv_qs:
            try:
                if not inv.currency_id or inv.currency.code == 'BOB':
                    continue

                scale = max(int(inv.currency.scale_factor or 1), 1)
                stock = _q(inv.total_balance or 0)
                if stock <= 0:
                    continue

                rate = (rates_activas.get(inv.currency_id)
                        or rates_fallback.get(inv.currency_id))

                if not rate:
                    resultado['advertencias'].append(
                        f"Sin tasa de venta activa para {inv.currency.code} — excluido"
                    )
                    continue

                sell = _q(rate.sell_rate or 0)
                if sell <= 0:
                    resultado['advertencias'].append(
                        f"Tasa de venta cero para {inv.currency.code} — excluido"
                    )
                    continue

                tc_venta_real = _q(sell / Decimal(str(scale)), RATE_Q)
                valor_bob     = _q(stock * tc_venta_real)

                key = inv.currency.code
                if key in resultado['divisas']:
                    resultado['divisas'][key]['stock'] = str(
                        _q(Decimal(resultado['divisas'][key]['stock']) + stock)
                    )
                    resultado['divisas'][key]['valor_bob'] = str(
                        _q(Decimal(resultado['divisas'][key]['valor_bob']) + valor_bob)
                    )
                else:
                    resultado['divisas'][key] = {
                        'code':          key,
                        'name':          inv.currency.name,
                        'scale_factor':  scale,
                        'stock':         str(_q(stock)),
                        'tc_venta_lote': str(rate.sell_rate),
                        'tc_venta_unit': str(tc_venta_real),
                        'tc_compra_lote':str(rate.buy_rate),
                        'valor_bob':     str(valor_bob),
                        'market_type':   rate.market_type,
                        'branch':        inv.branch.name if inv.branch_id else 'N/A',
                    }

                total_divisas += valor_bob

            except Exception as exc:
                resultado['advertencias'].append(
                    f"Error procesando inventario id={inv.pk}: {exc}"
                )

        resultado['totales']['divisas_bob'] = str(_q(total_divisas))

        # ── B+C) EFECTIVO Y DIGITAL (desde CapitalComposicion vigente) ────────
        comp_qs = CapitalComposicion.objects.filter(fecha=timezone.localdate())
        if branch:
            comp_qs = comp_qs.filter(branch=branch)

        total_efectivo  = _q(0)
        total_digital   = _q(0)
        total_pasivos   = _q(0)

        fuertes = caja_chica = monedas = rotos = sueltos = _q(0)
        qr      = tarjetas_tel = _q(0)

        for comp in comp_qs:
            fuertes       += _q(comp.fuertes       or 0)
            caja_chica    += _q(comp.caja_chica    or 0)
            monedas       += _q(comp.monedas       or 0)
            rotos         += _q(comp.rotos         or 0)
            sueltos       += _q(comp.sueltos       or 0)
            qr            += _q(comp.qr_transferencias   or 0)
            tarjetas_tel  += _q(comp.tarjetas_telefonicas or 0)
            total_pasivos += _q(comp.pasivos       or 0)

        total_efectivo = _q(fuertes + caja_chica + monedas + rotos + sueltos)
        total_digital  = _q(qr + tarjetas_tel)

        resultado['efectivo'] = {
            'fuertes':    str(_q(fuertes)),
            'caja_chica': str(_q(caja_chica)),
            'monedas':    str(_q(monedas)),
            'rotos':      str(_q(rotos)),
            'sueltos':    str(_q(sueltos)),
            'total':      str(total_efectivo),
        }
        resultado['digital'] = {
            'qr_transferencias':    str(_q(qr)),
            'tarjetas_telefonicas': str(_q(tarjetas_tel)),
            'total':                str(total_digital),
        }
        resultado['totales']['efectivo_bob'] = str(total_efectivo)
        resultado['totales']['digital_bob']  = str(total_digital)

        # ── D) TARJETAS MÓDULO (inventario físico de tarjetas tel.) ──────────
        total_tarjetas = _q(0)
        try:
            from tarjetas.models import TipoTarjeta, VentaTarjeta
            tipos = TipoTarjeta.objects.filter(is_active=True)
            for tipo in tipos:
                stock = tipo.stock_actual
                if stock == 0:
                    continue
                precio_prom = (
                    VentaTarjeta.objects
                    .filter(tipo_tarjeta=tipo)
                    .exclude(estado='ANULADA')
                    .order_by('-created_at')[:30]
                    .aggregate(avg=Avg('precio_venta'))['avg']
                ) or tipo.denominacion
                valor = _q(Decimal(str(precio_prom)) * stock)
                resultado['tarjetas_modulo'][tipo.nombre] = {
                    'stock':       stock,
                    'precio_prom': str(_q(Decimal(str(precio_prom)))),
                    'valor_bob':   str(valor),
                }
                total_tarjetas += valor
        except Exception as exc:
            resultado['advertencias'].append(f'Módulo tarjetas error: {exc}')

        resultado['totales']['tarjetas_bob'] = str(_q(total_tarjetas))

        # ── TOTALES ───────────────────────────────────────────────────────────
        total_activos = _q(
            total_divisas + total_efectivo + total_digital + total_tarjetas
        )
        capital_neto  = _q(total_activos - total_pasivos)

        resultado['total_activos'] = str(total_activos)
        resultado['total_pasivos'] = str(_q(total_pasivos))
        resultado['capital_neto']  = str(capital_neto)

        return resultado

    @staticmethod
    def guardar_snapshot(branch, generado_por, tipo='MANUAL',
                         efectivo_bob=None, qr_bob=None,
                         pasivos_bob=None, notas='') -> 'CapitalSnapshot':
        from .models import CapitalSnapshot
        from django.db import transaction as db_tx

        def _safe_dec(val, fallback='0') -> Decimal:
            try:
                v = val if val is not None else fallback
                return Decimal(str(v or fallback)).max(Decimal('0'))
            except Exception:
                return Decimal('0')

        with db_tx.atomic():
            try:
                capital = CapitalService.calcular_capital(branch=branch)
            except Exception as exc:
                log.exception('CAPITAL_CALC_ERROR branch=%s', branch)
                capital = {
                    'totales': {
                        'efectivo_bob': '0', 'digital_bob': '0',
                        'divisas_bob': '0', 'tarjetas_bob': '0',
                    },
                    'total_pasivos': '0',
                    'capital_neto': '0',
                    'divisas': {},
                    'tarjetas_modulo': {},
                    'advertencias': [f'Error calculando capital: {exc}'],
                }

            totales = capital.get('totales', {})

            ebo = _safe_dec(efectivo_bob) or _safe_dec(totales.get('efectivo_bob'))
            qbo = _safe_dec(qr_bob)       or _safe_dec(totales.get('digital_bob'))
            dbo = _safe_dec(totales.get('divisas_bob'))
            tbo = _safe_dec(totales.get('tarjetas_bob'))
            pbo = _safe_dec(pasivos_bob)  or _safe_dec(capital.get('total_pasivos'))
            total = _safe_dec(capital.get('capital_neto'))

            MAX_DEC = Decimal('9999999999999999.99')
            for v in (ebo, qbo, dbo, tbo, pbo, total):
                if v > MAX_DEC:
                    raise ValueError(f'Valor fuera de rango: {v}')

            snap = CapitalSnapshot.objects.create(
                fecha            = timezone.localdate(),
                branch           = branch,
                efectivo_bob     = ebo,
                qr_bob           = qbo,
                divisas_bob      = dbo,
                tarjetas_bob     = tbo,
                pasivos_bob      = pbo,
                total_bob        = total,
                detalle_divisas  = capital.get('divisas', {}),
                detalle_tarjetas = capital.get('tarjetas_modulo', {}),
                tipo             = tipo,
                notas            = notas,
                generado_por     = generado_por,
            )

        log.info('CAPITAL_SNAPSHOT id=%s fecha=%s branch=%s neto=%s',
                 snap.id, snap.fecha, branch, snap.total_bob)
        return snap

    @staticmethod
    def upsert_composicion(branch, user, data: dict, motivo: str = '') -> 'CapitalComposicion':
        """
        Crea o actualiza la composición de capital del día.
        Registra historial de cambios automáticamente.
        """
        from .models import CapitalComposicion, CapitalComposicionHistory
        from django.db import transaction as db_tx

        CAMPOS = ('fuertes', 'caja_chica', 'monedas', 'rotos', 'sueltos',
                  'qr_transferencias', 'tarjetas_telefonicas', 'pasivos', 'notas')

        with db_tx.atomic():
            comp, created = CapitalComposicion.objects.select_for_update().get_or_create(
                branch=branch,
                fecha=timezone.localdate(),
                defaults={**{c: data.get(c, Decimal('0')) for c in CAMPOS
                             if c != 'notas'},
                          'notas':          data.get('notas', ''),
                          'registrado_por': user},
            )

            if not created:
                prev_snap = comp.to_snapshot_dict()
                for campo in CAMPOS:
                    if campo in data:
                        setattr(comp, campo, data[campo])
                comp.save()

                CapitalComposicionHistory.objects.create(
                    composicion    = comp,
                    snapshot_prev  = prev_snap,
                    snapshot_new   = comp.to_snapshot_dict(),
                    motivo         = motivo or 'Actualización manual',
                    modificado_por = user,
                )

        log.info('CAPITAL_COMPOSICION branch=%s fecha=%s created=%s by=%s',
                 branch, comp.fecha, created, user.username)
        return comp


# ─────────────────────────────────────────────────────────────────────────────
#  GananciaService — sin cambios respecto a versión anterior
# ─────────────────────────────────────────────────────────────────────────────

class GananciaService:
    """
    Calcula ganancias por divisa usando spreads reales de las transacciones.

    Metodología:
      - BUY:  casa compra divisa del cliente  → entrega BOB (costo)
      - SELL: casa vende divisa al cliente    → recibe BOB (ingreso)
      - ganancia_divisa = total_ingreso_bob - total_costo_bob
    """

    @staticmethod
    def ganancia_por_divisa(date_from: date, date_to: date,
                            branch=None, currency_code: str = None) -> list:
        from transactions.models import Transaction

        qs = Transaction.objects.filter(
            status='COMPLETED',
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
        )
        if branch:
            qs = qs.filter(branch=branch)

        codes = set(
            qs.exclude(currency_from__code='BOB')
              .values_list('currency_from__code', flat=True)
        ) | set(
            qs.exclude(currency_to__code='BOB')
              .values_list('currency_to__code', flat=True)
        )

        if currency_code:
            codes = {currency_code} & codes

        resultado = []
        for code in sorted(codes):
            compras = qs.filter(
                transaction_type='BUY', currency_from__code=code,
            ).aggregate(ops=Count('id'), unidades=Sum('amount_from'), costo_bob=Sum('amount_to'))

            ventas = qs.filter(
                transaction_type='SELL', currency_to__code=code,
            ).aggregate(ops=Count('id'), unidades=Sum('amount_to'), ingreso_bob=Sum('amount_from'))

            costo_bob   = _q(compras['costo_bob']  or 0)
            ingreso_bob = _q(ventas['ingreso_bob'] or 0)
            unid_comp   = _q(compras['unidades']   or 0)
            unid_vend   = _q(ventas['unidades']    or 0)
            ganancia    = _q(ingreso_bob - costo_bob)

            tc_comp = _q(costo_bob   / unid_comp, RATE_Q) if unid_comp > 0 else _q(0, RATE_Q)
            tc_vend = _q(ingreso_bob / unid_vend, RATE_Q) if unid_vend > 0 else _q(0, RATE_Q)

            resultado.append({
                'divisa':              code,
                'ops_compra':          compras['ops'] or 0,
                'ops_venta':           ventas['ops']  or 0,
                'unidades_compradas':  str(unid_comp),
                'unidades_vendidas':   str(unid_vend),
                'costo_bob':           str(costo_bob),
                'ingreso_bob':         str(ingreso_bob),
                'ganancia_bob':        str(ganancia),
                'tc_compra_prom':      str(tc_comp),
                'tc_venta_prom':       str(tc_vend),
                'spread_prom':         str(_q(tc_vend - tc_comp, RATE_Q)),
                'margen_pct':          str(
                    _q(ganancia / costo_bob * 100) if costo_bob > 0 else _q(0)
                ),
            })

        resultado.sort(key=lambda x: Decimal(x['ganancia_bob']), reverse=True)
        return resultado

    @staticmethod
    def resumen_financiero(date_from: date, date_to: date, branch=None) -> dict:
        from .models import Gasto
        from tarjetas.models import VentaTarjeta

        ganancias_div = GananciaService.ganancia_por_divisa(date_from, date_to, branch)
        total_div     = sum(Decimal(g['ganancia_bob']) for g in ganancias_div)

        # Excluir anuladas: su ganancia_bob queda registrada para auditoría
        # pero no debe contar en el P&L.
        vt_qs = VentaTarjeta.objects.filter(
            created_at__date__gte=date_from, created_at__date__lte=date_to
        ).exclude(estado='ANULADA')
        if branch:
            vt_qs = vt_qs.filter(branch=branch)
        vt_agg = vt_qs.aggregate(
            total_ganancia=Sum('ganancia_bob'),
            total_ventas=Count('id'),
            total_ingresos=Sum('total_bob'),
        )
        total_tarjetas = _q(vt_agg['total_ganancia'] or 0)

        gasto_qs = Gasto.objects.filter(fecha__gte=date_from, fecha__lte=date_to)
        if branch:
            gasto_qs = gasto_qs.filter(branch=branch)
        gasto_agg = gasto_qs.aggregate(total_gastos=Sum('monto_bob'), count=Count('id'))
        total_gastos = _q(gasto_agg['total_gastos'] or 0)

        gastos_cat = list(
            gasto_qs.values('categoria')
            .annotate(total=Sum('monto_bob'), count=Count('id'))
            .order_by('-total')
        )

        ganancia_bruta = _q(total_div + total_tarjetas)
        ganancia_neta  = _q(ganancia_bruta - total_gastos)

        return {
            'periodo':             {'desde': str(date_from), 'hasta': str(date_to)},
            'ganancias_divisas':   {'total': str(_q(total_div)), 'detalle': ganancias_div},
            'ganancias_tarjetas':  {
                'total':    str(total_tarjetas),
                'ventas':   vt_agg['total_ventas']   or 0,
                'ingresos': str(_q(vt_agg['total_ingresos'] or 0)),
            },
            'gastos': {
                'total':         str(total_gastos),
                'count':         gasto_agg['count'] or 0,
                'por_categoria': [{**g, 'total': str(_q(g['total']))} for g in gastos_cat],
            },
            'ganancia_bruta': str(ganancia_bruta),
            'ganancia_neta':  str(ganancia_neta),
        }


# ─────────────────────────────────────────────────────────────────────────────
#  CashBOBService — denominación-level BOB cash management
# ─────────────────────────────────────────────────────────────────────────────

class InsufficientCashError(Exception):
    """Raised when a BOB deduction cannot be satisfied from available cash."""


class CashBOBService:
    """
    Manages the physical BOB cash structure.

    Denomination priority for deductions:
      caja_chica (10→200) → sueltos (10→20) → fuertes (50→200)

    NEVER allows negative denomination counts.
    """

    # ── Snapshot helpers ──────────────────────────────────────────────────────

    @staticmethod
    def get_or_create_today(branch, user) -> 'CashBOB':
        from .models import CashBOB
        obj, _ = CashBOB.objects.get_or_create(
            branch=branch,
            fecha=timezone.localdate(),
            defaults={'registrado_por': user},
        )
        return obj

    @staticmethod
    def serialize_breakdown(cash: 'CashBOB') -> dict:
        """
        Returns the structured breakdown consumed by GET /api/capital/cash-bob/hoy/.
        {
          "fuertes":    {"200": x, "100": x, "50": x, "total": x},
          "sueltos":    {"20": x, "10": x, "total": x},
          "caja_chica": {"200": x, ..., "10": x, "total": x},
          "qr":         x,
          "total_efectivo_fisico": x,
          "total_bob":  x,
        }
        """
        tf  = str(cash.total_fuertes())
        ts  = str(cash.total_sueltos())
        tcc = str(cash.total_caja_chica())
        return {
            'fecha': str(cash.fecha),
            'branch': cash.branch_id,
            'branch_nombre': cash.branch.name,
            'fuertes': {
                '200':   cash.fuertes_200,
                '100':   cash.fuertes_100,
                '50':    cash.fuertes_50,
                'total': tf,
            },
            'sueltos': {
                '20':    cash.sueltos_20,
                '10':    cash.sueltos_10,
                'total': ts,
            },
            'caja_chica': {
                '200':   cash.caja_chica_200,
                '100':   cash.caja_chica_100,
                '50':    cash.caja_chica_50,
                '20':    cash.caja_chica_20,
                '10':    cash.caja_chica_10,
                'total': tcc,
            },
            'qr': str(cash.qr_transferencias),
            'total_efectivo_fisico': str(cash.total_efectivo_fisico()),
            'total_bob': str(cash.total_general_bob()),
            'updated_at': cash.updated_at.isoformat(),
        }

    # ── Write ─────────────────────────────────────────────────────────────────

    @staticmethod
    def upsert(branch, user, data: dict) -> 'CashBOB':
        """
        Create or fully update CashBOB for today.
        After saving, syncs aggregated totals to CapitalComposicion.
        """
        from .models import CashBOB
        from django.db import transaction as db_tx

        FIELDS = (
            'fuertes_200', 'fuertes_100', 'fuertes_50',
            'sueltos_20', 'sueltos_10',
            'caja_chica_200', 'caja_chica_100', 'caja_chica_50',
            'caja_chica_20', 'caja_chica_10',
            'qr_transferencias',
        )

        with db_tx.atomic():
            cash, created = CashBOB.objects.select_for_update().get_or_create(
                branch=branch,
                fecha=timezone.localdate(),
                defaults={
                    **{f: data.get(f, 0) for f in FIELDS},
                    'registrado_por': user,
                },
            )
            if not created:
                for field in FIELDS:
                    if field in data:
                        setattr(cash, field, data[field])
                cash.save()

            # Keep CapitalComposicion in sync
            CashBOBService._sync_to_composicion(branch, user, cash)

        log.info('CASH_BOB branch=%s fecha=%s created=%s total=%s',
                 branch, cash.fecha, created, cash.total_general_bob())
        return cash

    @staticmethod
    def _sync_to_composicion(branch, user, cash: 'CashBOB'):
        """Push aggregated CashBOB totals into CapitalComposicion."""
        CapitalService.upsert_composicion(
            branch=branch,
            user=user,
            data={
                'fuertes':          cash.total_fuertes(),
                'sueltos':          cash.total_sueltos(),
                'caja_chica':       cash.total_caja_chica(),
                'qr_transferencias': cash.qr_transferencias,
            },
            motivo='Sync desde CashBOB',
        )

    # ── Deduction (forex transaction integration) ─────────────────────────────

    @staticmethod
    def deducir_bob(branch, amount: Decimal, save: bool = True) -> dict:
        """
        Deduct ``amount`` BOB from physical cash in priority order:
          1. caja_chica (10 → 200 Bs)
          2. sueltos    (10 → 20 Bs)
          3. fuertes    (50 → 200 Bs)

        Raises InsufficientCashError if:
          - total_efectivo_fisico < amount
          - exact change cannot be made with available denominations

        Returns dict with deduction log.
        """
        from .models import CashBOB
        from django.db import transaction as db_tx

        with db_tx.atomic():
            cash = CashBOB.objects.select_for_update().get(
                branch=branch, fecha=timezone.localdate()
            )

            total_fisica = cash.total_efectivo_fisico()
            if total_fisica < amount:
                raise InsufficientCashError(
                    f'Saldo insuficiente: disponible Bs. {total_fisica}, '
                    f'requerido Bs. {amount}'
                )

            # Denominaciones en orden de prioridad (caja_chica → sueltos →
            # fuertes, billete menor primero). El solver prefiere ese orden
            # pero hace backtracking: el greedy puro fallaba en combinaciones
            # resolubles (p.ej. 50 Bs con 10×4 + 20×2 → tomaba 10×4 y quedaba
            # sin cambio para los 10 restantes).
            denoms = [
                ('caja_chica', 'caja_chica_10',  10),
                ('caja_chica', 'caja_chica_20',  20),
                ('caja_chica', 'caja_chica_50',  50),
                ('caja_chica', 'caja_chica_100', 100),
                ('caja_chica', 'caja_chica_200', 200),
                ('sueltos',    'sueltos_10',     10),
                ('sueltos',    'sueltos_20',     20),
                ('fuertes',    'fuertes_50',     50),
                ('fuertes',    'fuertes_100',    100),
                ('fuertes',    'fuertes_200',    200),
            ]
            disponibles = [
                (group, field, value, getattr(cash, field))
                for group, field, value in denoms
            ]
            combo = CashBOBService._find_exact_combo(
                disponibles, int(amount)
            )
            if combo is None:
                raise InsufficientCashError(
                    f'No se puede dar cambio exacto de Bs. {amount} '
                    f'con las denominaciones disponibles'
                )

            ops = []
            for (group, field, value, available), use in zip(disponibles, combo):
                if use == 0:
                    continue
                setattr(cash, field, available - use)
                ops.append({
                    'grupo':        group,
                    'campo':        field,
                    'denominacion': value,
                    'billetes':     use,
                    'monto_bob':    use * value,
                })

            if save:
                cash.save()

        return {
            'deducted_bob': str(amount),
            'operations':   ops,
            'saldo_previo': str(total_fisica),
            'saldo_nuevo':  str(cash.total_efectivo_fisico()),
        }

    @staticmethod
    def _find_exact_combo(disponibles: list, amount: int):
        """
        Busca una combinación exacta de billetes para ``amount``.

        ``disponibles``: [(group, field, value, available), ...] en orden de
        prioridad. Prueba primero el máximo de cada denominación preferida
        (equivalente al greedy anterior) y hace backtracking cuando el resto
        no tiene solución. Memoiza estados (idx, remaining) infactibles.

        Returns:
            list[int] con billetes a usar por posición, o None si no hay
            combinación exacta.
        """
        n = len(disponibles)
        infeasible = set()

        def _dfs(idx: int, remaining: int):
            if remaining == 0:
                return [0] * (n - idx)
            if idx == n or (idx, remaining) in infeasible:
                return None
            value     = disponibles[idx][2]
            available = disponibles[idx][3]
            for use in range(min(available, remaining // value), -1, -1):
                rest = _dfs(idx + 1, remaining - use * value)
                if rest is not None:
                    return [use] + rest
            infeasible.add((idx, remaining))
            return None

        if amount <= 0:
            return [0] * n
        return _dfs(0, amount)


def _serialize_resultado(r):
    """Convierte Decimals a str recursivamente para serialización JSON."""
    if isinstance(r, Decimal):
        return str(r)
    if isinstance(r, dict):
        return {k: _serialize_resultado(v) for k, v in r.items()}
    if isinstance(r, list):
        return [_serialize_resultado(v) for v in r]
    return r
