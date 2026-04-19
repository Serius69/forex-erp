# tarjetas/services.py
"""
Motor de negocio para tarjetas telefónicas.
Toda la lógica financiera crítica vive aquí — no en vistas ni serializers.
"""
import logging
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction as db_tx
from django.utils import timezone

from .models import TipoTarjeta, LoteCompra, VentaTarjeta, DetalleVentaLote, MovimientoTarjeta

log = logging.getLogger('tarjetas')
MONEY_Q = Decimal('0.01')


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
        return venta

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
