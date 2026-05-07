# tarjetas/services.py
"""
Motor de negocio para tarjetas telefónicas.
Toda la lógica financiera crítica vive aquí — no en vistas ni serializers.
"""
import logging
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction as db_tx
from django.utils import timezone

from .models import (
    TipoTarjeta, LoteCompra, VentaTarjeta, DetalleVentaLote,
    MovimientoTarjeta, AlertaInventarioTarjeta,
)

log = logging.getLogger('tarjetas')
MONEY_Q = Decimal('0.01')


def _publish_inventario_ws():
    """Publica snapshot de inventario al grupo WS 'tarjetas_inventario'."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        layer = get_channel_layer()
        if layer is None:
            return
        snapshot = TarjetaService.get_posicion_inventario()
        async_to_sync(layer.group_send)(
            'tarjetas_inventario',
            {'type': 'inventario_update', 'data': snapshot},
        )
    except Exception:
        pass  # Silencioso cuando Redis/Channels no está disponible en dev


class TarjetaService:

    # ── Compra de lote ────────────────────────────────────────────────────────

    @staticmethod
    @db_tx.atomic
    def registrar_lote(
        tipo_tarjeta: TipoTarjeta,
        cantidad: int,
        precio_costo: Decimal,
        registrado_por,
        proveedor: str = 'Proveedor',
        numero_factura: str = '',
        notas: str = '',
        fecha_compra=None,
        branch=None,
    ) -> LoteCompra:
        """
        Registra un lote de compra de tarjetas.
        Devuelve el lote creado.
        También escribe un MovimientoTarjeta de tipo COMPRA para el libro diario.
        """
        precio_costo = Decimal(str(precio_costo))
        lote = LoteCompra.objects.create(
            tipo_tarjeta     = tipo_tarjeta,
            cantidad_total   = cantidad,
            cantidad_restante= cantidad,
            precio_costo     = precio_costo,
            proveedor        = proveedor,
            numero_factura   = numero_factura,
            registrado_por   = registrado_por,
            notas            = notas,
            fecha_compra     = fecha_compra or timezone.localdate(),
        )
        total = (precio_costo * cantidad).quantize(MONEY_Q)
        MovimientoTarjeta.objects.create(
            tipo_movimiento = 'COMPRA',
            tipo_tarjeta    = tipo_tarjeta,
            cantidad        = cantidad,
            precio_unitario = precio_costo,
            total_bob       = total,
            ganancia_bob    = None,
            lote_compra     = lote,
            usuario         = registrado_por,
            branch          = branch or getattr(registrado_por, 'branch', None),
            notas           = notas,
        )
        log.info(
            "LOTE_COMPRA id=%s tipo=%s cantidad=%s costo_unit=%s total=%s",
            lote.id, tipo_tarjeta, cantidad, precio_costo, total,
        )
        # Publicar cambio de inventario por WebSocket (fuera de la transacción)
        from django.db import transaction as _tx
        _tx.on_commit(_publish_inventario_ws)
        return lote

    # ── Venta de tarjetas (FIFO) ──────────────────────────────────────────────

    @staticmethod
    @db_tx.atomic
    def registrar_venta(
        tipo_tarjeta: TipoTarjeta,
        cantidad: int,
        precio_venta: Decimal,
        cajero,
        branch,
        medio_pago: str = 'CASH',
        cliente_nombre: str = '',
        cliente_tel: str = '',
        notas: str = '',
        comision_bob: Decimal = Decimal('0'),
    ) -> VentaTarjeta:
        """
        Registra la venta de `cantidad` tarjetas del tipo dado.

        Algoritmo FIFO:
          - Itera los lotes ordenados por fecha_compra ASC (más antiguo primero)
          - Consume unidades de cada lote hasta completar `cantidad`
          - Registra el detalle en DetalleVentaLote para trazabilidad
          - Calcula la ganancia real: sum(precio_venta - costo_lote) * uds

        Raises:
          ValueError si no hay stock suficiente.
        """
        precio_venta = Decimal(str(precio_venta))

        # Verificar stock antes de hacer cualquier cambio
        stock = tipo_tarjeta.stock_actual
        if cantidad > stock:
            raise ValueError(
                f"Stock insuficiente de {tipo_tarjeta}. "
                f"Disponible: {stock}, solicitado: {cantidad}."
            )

        # Generar número de venta único
        from django.db.models import Max
        hoy     = timezone.localdate()
        prefix  = f"TV{hoy.strftime('%Y%m%d')}"
        ultimo  = (VentaTarjeta.objects
                   .select_for_update()
                   .filter(numero_venta__startswith=prefix)
                   .aggregate(m=Max('numero_venta'))['m'])
        seq = int(ultimo[-4:]) + 1 if ultimo else 1
        numero_venta = f"{prefix}{seq:04d}"

        # Crear registro de venta
        comision_bob  = Decimal(str(comision_bob or '0'))
        total_base    = (precio_venta * cantidad).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
        total_con_com = (total_base + comision_bob).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
        venta = VentaTarjeta(
            numero_venta       = numero_venta,
            tipo_tarjeta       = tipo_tarjeta,
            cantidad           = cantidad,
            precio_venta       = precio_venta,
            total_bob          = total_base,
            comision_bob       = comision_bob,
            total_con_comision = total_con_com,
            medio_pago         = medio_pago,
            cliente_nombre     = cliente_nombre,
            cliente_tel        = cliente_tel,
            notas              = notas,
            cajero             = cajero,
            branch             = branch,
        )
        venta.save()

        # FIFO: consumir lotes en orden
        restante          = cantidad
        costo_fifo_total  = Decimal('0')

        lotes_fifo = (LoteCompra.objects
                      .select_for_update()
                      .filter(tipo_tarjeta=tipo_tarjeta, is_active=True, cantidad_restante__gt=0)
                      .order_by('fecha_compra', 'id'))

        for lote in lotes_fifo:
            if restante == 0:
                break
            consumir = min(restante, lote.cantidad_restante)
            costo_lote = Decimal(str(lote.precio_costo))

            # Registrar detalle
            DetalleVentaLote.objects.create(
                venta             = venta,
                lote              = lote,
                cantidad_consumida= consumir,
                costo_unitario    = costo_lote,
            )

            # Actualizar lote
            lote.cantidad_restante -= consumir
            if lote.cantidad_restante == 0:
                lote.is_active = False
            lote.save(update_fields=['cantidad_restante', 'is_active', 'updated_at'])

            costo_fifo_total += costo_lote * consumir
            restante         -= consumir

        # Actualizar ganancia en la venta
        ganancia = (venta.total_bob - costo_fifo_total).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
        VentaTarjeta.objects.filter(pk=venta.pk).update(
            costo_fifo_bob = costo_fifo_total.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP),
            ganancia_bob   = ganancia,
        )
        venta.refresh_from_db()

        # Libro diario: movimiento VENTA
        MovimientoTarjeta.objects.create(
            tipo_movimiento = 'VENTA',
            tipo_tarjeta    = tipo_tarjeta,
            cantidad        = cantidad,
            precio_unitario = precio_venta,
            total_bob       = venta.total_bob,
            ganancia_bob    = ganancia,
            venta_tarjeta   = venta,
            usuario         = cajero,
            branch          = branch,
            notas           = notas,
        )

        log.info(
            "VENTA_TARJETA id=%s num=%s tipo=%s cant=%s pvta=%s ganancia=%s cajero=%s",
            venta.id, numero_venta, tipo_tarjeta,
            cantidad, precio_venta, ganancia, cajero.username,
        )
        from django.db import transaction as _tx
        _tx.on_commit(_publish_inventario_ws)
        return venta

    # ── Anulación de venta ────────────────────────────────────────────────────

    @staticmethod
    @db_tx.atomic
    def anular_venta(venta: VentaTarjeta, motivo: str, anulado_por) -> VentaTarjeta:
        """
        Anula una venta ya registrada.

        Devuelve las unidades a los lotes originales (según DetalleVentaLote).
        Si el lote estaba agotado, lo reactiva. Requiere motivo.
        """
        if not motivo or not motivo.strip():
            raise ValueError("El motivo de anulación es obligatorio.")
        if venta.estado == 'ANULADA':
            raise ValueError(f"La venta {venta.numero_venta} ya está anulada.")

        for detalle in venta.detalles_lote.select_for_update().select_related('lote'):
            lote = detalle.lote
            lote.cantidad_restante += detalle.cantidad_consumida
            lote.is_active = True
            lote.save(update_fields=['cantidad_restante', 'is_active', 'updated_at'])

        VentaTarjeta.objects.filter(pk=venta.pk).update(
            estado           = 'ANULADA',
            motivo_anulacion = motivo.strip(),
            anulado_por      = anulado_por,
            anulado_at       = timezone.now(),
        )
        venta.refresh_from_db()

        MovimientoTarjeta.objects.create(
            tipo_movimiento = 'COMPRA',
            tipo_tarjeta    = venta.tipo_tarjeta,
            cantidad        = venta.cantidad,
            precio_unitario = venta.costo_fifo_bob / venta.cantidad if venta.cantidad else Decimal('0'),
            total_bob       = venta.costo_fifo_bob,
            ganancia_bob    = None,
            usuario         = anulado_por,
            branch          = venta.branch,
            notas           = f"Anulación venta {venta.numero_venta}: {motivo}",
        )
        log.info(
            "VENTA_ANULADA id=%s num=%s motivo=%s by=%s",
            venta.id, venta.numero_venta, motivo, anulado_por.username,
        )
        from django.db import transaction as _tx
        _tx.on_commit(_publish_inventario_ws)
        return venta

    # ── Posición de inventario valorizada ─────────────────────────────────────

    @staticmethod
    def get_posicion_inventario(branch=None) -> dict:
        """
        Posición valorizada del inventario agrupada por tipo de tarjeta.
        Para cada tipo: stock, valor costo, valor venta, margen potencial, lotes activos.
        """
        from django.db.models import Sum
        tipos = TipoTarjeta.objects.filter(is_active=True).prefetch_related(
            'lotes', 'alertas_inventario',
        )

        items = []
        total_unidades = 0
        total_costo    = Decimal('0')
        total_venta    = Decimal('0')

        for t in tipos:
            lotes_activos = list(
                t.lotes.filter(is_active=True, cantidad_restante__gt=0)
                .order_by('fecha_compra')
            )
            stock = sum(l.cantidad_restante for l in lotes_activos)
            costo_prom = t.costo_promedio
            valor_costo = t.valor_inventario_bob
            valor_venta = (t.denominacion * stock).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
            margen_potencial = (valor_venta - valor_costo).quantize(MONEY_Q, rounding=ROUND_HALF_UP)

            alerta = t.alertas_inventario.filter(
                is_active=True,
                branch=branch,
            ).first() or t.alertas_inventario.filter(
                is_active=True, branch__isnull=True,
            ).first()

            estado_stock = 'ok'
            if alerta:
                if stock <= alerta.stock_critico:
                    estado_stock = 'critico'
                elif stock <= alerta.stock_minimo:
                    estado_stock = 'bajo'

            items.append({
                'id':                t.id,
                'nombre':            t.nombre,
                'operadora':         t.operadora,
                'denominacion':      str(t.denominacion),
                'stock':             stock,
                'lotes_activos':     len(lotes_activos),
                'costo_promedio':    str(costo_prom),
                'valor_costo_bob':   str(valor_costo),
                'valor_venta_bob':   str(valor_venta),
                'margen_potencial':  str(margen_potencial),
                'estado_stock':      estado_stock,
                'stock_minimo':      alerta.stock_minimo if alerta else None,
                'stock_critico':     alerta.stock_critico if alerta else None,
            })
            total_unidades += stock
            total_costo    += valor_costo
            total_venta    += valor_venta

        return {
            'timestamp': timezone.now().isoformat(),
            'resumen': {
                'total_tipos':     len(items),
                'total_unidades':  total_unidades,
                'valor_costo_bob': str(total_costo.quantize(MONEY_Q)),
                'valor_venta_bob': str(total_venta.quantize(MONEY_Q)),
                'margen_potencial': str((total_venta - total_costo).quantize(MONEY_Q)),
            },
            'items': items,
        }

    # ── Consultas de inventario ───────────────────────────────────────────────

    @staticmethod
    def inventario_completo(branch=None) -> list:
        """
        Devuelve snapshot del inventario de tarjetas.
        branch: filtrar por sucursal (futuro soporte multi-branch).
        """
        tipos = TipoTarjeta.objects.filter(is_active=True).prefetch_related(
            'lotes'
        )
        result = []
        for t in tipos:
            result.append({
                'id':                   t.id,
                'nombre':               t.nombre,
                'operadora':            t.operadora,
                'denominacion':         str(t.denominacion),
                'stock_actual':         t.stock_actual,
                'costo_promedio':       str(t.costo_promedio),
                'valor_inventario_bob': str(t.valor_inventario_bob),
            })
        return result
