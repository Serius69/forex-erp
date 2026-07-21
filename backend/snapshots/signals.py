# snapshots/signals.py
"""
Señales Django que disparan SystemSnapshots automáticos.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  REGLAS DE DISPARO (snapshot se crea SI Y SOLO SI):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  DISPARADORES ACTIVOS
  ┌─────────────────────────────────────────────────────────────────┐
  │ 1. Transacción forex COMPLETADA        Transaction(COMPLETED)   │
  │ 2. Transacción forex REVERTIDA         Transaction(REVERSED)    │
  │ 3. Venta de tarjeta                    VentaTarjeta (create)    │
  │ 4. Compra de lote de tarjetas          LoteCompra (create)      │
  │ 5. Gasto operativo registrado          Gasto (create)           │
  │ 6. Composición de capital actualizada  CapitalComposicion (*)   │
  │ 7. Caja BOB actualizada                CashBOB (*)              │
  │ 8. Movimiento de inventario            InventoryMovement (create)│
  │ 9. Transferencia de inventario         InventoryTransfer        │
  │                                        (status → COMPLETED)     │
  │ 10. Apertura diaria / Cierre diario    Celery Beat              │
  └─────────────────────────────────────────────────────────────────┘

  NO DISPARADORES (explícitamente ignorados)
  ┌─────────────────────────────────────────────────────────────────┐
  │ · Lecturas, vistas de dashboard, endpoints GET                  │
  │ · Transacciones PENDING o CANCELLED                             │
  │ · Actualizaciones de tasas de cambio (datos de mercado)         │
  │ · Guardados de CapitalSnapshot (evita bucle infinito)           │
  │ · Transferencias PENDING / IN_TRANSIT / CANCELLED               │
  │ · Ediciones de gastos ya registrados (solo creación cuenta)     │
  └─────────────────────────────────────────────────────────────────┘

  DEBOUNCE POR MÓDULO (evita rafagas)
  ┌───────────────┬────────────────┐
  │ forex         │ 10 s           │
  │ tarjetas      │ 10 s           │
  │ capital       │ 30 s (default) │
  │ caja_bob      │ 30 s (default) │
  │ gastos        │ 60 s           │
  │ inventory     │ 30 s (default) │
  │ system        │ 0 s (forzado)  │
  └───────────────┴────────────────┘

  GARANTÍA: schedule() usa transaction.on_commit() — el snapshot se
  crea SOLO si la transacción BD principal hizo commit con éxito.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .services import SnapshotService
from .models import SystemSnapshot

log = logging.getLogger('snapshots')

# Debounce por módulo (segundos).  0 / None = forzado (sin debounce).
_DEBOUNCE: dict = {
    'forex':     10,
    'tarjetas':  10,
    'capital':   30,
    'caja_bob':  30,
    'gastos':    60,
    'inventory': 30,
    'system':    0,
}


def _schedule(module: str, action: str, instance, metadata: dict):
    """
    Obtiene branch y usuario del objeto y encola el snapshot.
    Nunca propaga excepciones — la señal no debe romper el flujo principal.
    """
    try:
        branch = (
            getattr(instance, 'branch', None)
            or getattr(instance, 'source_branch', None)
            or getattr(instance, 'sucursal', None)
        )
        user = (
            getattr(instance, 'cashier', None)
            or getattr(instance, 'cajero', None)
            or getattr(instance, 'registrado_por', None)
            or getattr(instance, 'generado_por', None)
            or getattr(instance, 'user', None)
        )

        debounce = _DEBOUNCE.get(module, 30)
        force    = (debounce == 0)

        SnapshotService.schedule(
            module          = module,
            action          = action,
            user            = user,
            branch          = branch,
            metadata        = metadata,
            debounce_seconds= debounce,
            force           = force,
        )
    except Exception as exc:
        log.error(
            'SIGNAL_SCHEDULE_FAILED module=%s action=%s instance=%s err=%s',
            module, action, repr(instance), exc, exc_info=True,
        )


# ── 1 & 2 — Transacciones Forex ──────────────────────────────────────────────

@receiver(post_save, sender='transactions.Transaction')
def on_forex_transaction_saved(sender, instance, created, **kwargs):
    """
    Dispara snapshot para transacciones COMPLETADAS o REVERTIDAS.

    COMPLETED (create)   → acción 'transaction'   (nueva operación)
    COMPLETED (update)   → acción 'transaction'   (PENDING→COMPLETED)
    REVERSED  (update)   → acción 'delete'         (reversa/anulación)

    Ignorar: PENDING, CANCELLED — no modifican capital real.
    """
    if instance.status == 'COMPLETED':
        action = 'transaction' if created else 'transaction'
    elif instance.status == 'REVERSED' and not created:
        action = 'delete'
    else:
        return  # PENDING, CANCELLED — no afectan capital

    _schedule(
        module   = 'forex',
        action   = action,
        instance = instance,
        metadata = {
            'tx_number':      instance.transaction_number,
            'tx_type':        instance.transaction_type,
            'status':         instance.status,
            'currency_from':  instance.currency_from.code if instance.currency_from_id else None,
            'currency_to':    instance.currency_to.code if instance.currency_to_id else None,
            'amount_from':    str(instance.amount_from),
            'amount_to':      str(instance.amount_to),
            'exchange_rate':  str(instance.exchange_rate),
            'payment_method': instance.payment_method,
        },
    )


# ── 3 — Ventas de tarjetas ────────────────────────────────────────────────────

@receiver(post_save, sender='tarjetas.VentaTarjeta')
def on_venta_tarjeta_saved(sender, instance, created, **kwargs):
    """Snapshot tras cada nueva venta de tarjeta prepago (FIFO)."""
    if not created:
        return

    _schedule(
        module   = 'tarjetas',
        action   = 'transaction',
        instance = instance,
        metadata = {
            'venta_id':     instance.id,
            'numero_venta': instance.numero_venta,
            'tipo_tarjeta': instance.tipo_tarjeta.nombre if instance.tipo_tarjeta_id else None,
            'cantidad':     instance.cantidad,
            'total_bob':    str(instance.total_bob),
            'ganancia_bob': str(instance.ganancia_bob),
        },
    )


# ── 4 — Compras de lotes de tarjetas ─────────────────────────────────────────

@receiver(post_save, sender='tarjetas.LoteCompra')
def on_lote_compra_saved(sender, instance, created, **kwargs):
    """Snapshot tras registrar un nuevo lote de compra de tarjetas."""
    if not created:
        return

    _schedule(
        module   = 'tarjetas',
        action   = 'create',
        instance = instance,
        metadata = {
            'lote_id':      instance.id,
            'tipo_tarjeta': instance.tipo_tarjeta.nombre if instance.tipo_tarjeta_id else None,
            'cantidad':     instance.cantidad_total,
            'precio_costo': str(instance.precio_costo),
            'proveedor':    instance.proveedor,
        },
    )


# ── 5 — Gastos operativos ────────────────────────────────────────────────────

@receiver(post_save, sender='capital.Gasto')
def on_gasto_saved(sender, instance, created, **kwargs):
    """
    Snapshot cuando se REGISTRA un nuevo gasto operativo.
    Las ediciones posteriores al mismo gasto NO disparan snapshot —
    una corrección de texto no cambia el capital ya impactado.
    """
    if not created:
        return  # Ediciones ignoradas intencionalmente

    _schedule(
        module   = 'gastos',
        action   = 'create',
        instance = instance,
        metadata = {
            'gasto_id':   instance.id,
            'categoria':  instance.categoria,
            'monto_bob':  str(instance.monto_bob),
            'medio_pago': instance.medio_pago,
            'fecha':      str(instance.fecha),
        },
    )


# ── 6 — Composición de capital (actualización manual de caja) ────────────────

@receiver(post_save, sender='capital.CapitalComposicion')
def on_composicion_saved(sender, instance, created, **kwargs):
    """
    Snapshot cuando cambia la composición de caja.
    Tanto apertura (create) como ajuste manual (update) son significativos.
    """
    action = 'create' if created else 'update'
    _schedule(
        module   = 'capital',
        action   = action,
        instance = instance,
        metadata = {
            'composicion_id': instance.id,
            'fecha':          str(instance.fecha),
            'total_efectivo': str(instance.total_efectivo),
            'total_digital':  str(instance.total_digital),
            'capital_neto':   str(instance.capital_neto_local),
        },
    )


# ── 7 — Caja BOB por denominación ────────────────────────────────────────────

@receiver(post_save, sender='capital.CashBOB')
def on_cash_bob_saved(sender, instance, created, **kwargs):
    """
    Snapshot cuando se actualiza el desglose de denominaciones BOB.
    Disparado por CashBOBService.upsert() después de una edición manual.
    """
    action = 'create' if created else 'update'
    _schedule(
        module   = 'caja_bob',
        action   = action,
        instance = instance,
        metadata = {
            'fecha':                  str(instance.fecha),
            'total_fuertes':          str(instance.total_fuertes()),
            'total_sueltos':          str(instance.total_sueltos()),
            'total_caja_chica':       str(instance.total_caja_chica()),
            'qr_transferencias':      str(instance.qr_transferencias),
            'total_efectivo_fisico':  str(instance.total_efectivo_fisico()),
            'total_bob':              str(instance.total_general_bob()),
        },
    )


# ── 8 — Movimientos de inventario ────────────────────────────────────────────

@receiver(post_save, sender='inventory.InventoryMovement')
def on_inventory_movement_saved(sender, instance, created, **kwargs):
    """
    Snapshot ante cualquier movimiento de inventario (IN/OUT/ADJUSTMENT/TRANSFER).
    Solo en creación — los movimientos son inmutables por diseño.
    """
    if not created:
        return

    currency_code = None
    branch        = None
    try:
        currency_code = instance.inventory.currency.code
        branch        = instance.inventory.branch
    except Exception:
        pass

    _schedule(
        module   = 'inventory',
        action   = 'transaction',
        instance = instance,
        metadata = {
            'movement_type': instance.movement_type,
            'currency':      currency_code,
            'amount':        str(instance.amount),
            'rate':          str(instance.rate),
            'balance_before':str(instance.balance_before),
            'balance_after': str(instance.balance_after),
            'reference':     instance.reference,
        },
    )


# ── 9 — Transferencias de inventario completadas ─────────────────────────────

@receiver(post_save, sender='inventory.InventoryTransfer')
def on_inventory_transfer_saved(sender, instance, created, **kwargs):
    """
    Snapshot cuando una transferencia de inventario alcanza estado COMPLETED.
    Estados PENDING / IN_TRANSIT / CANCELLED no afectan inventario físico aún.
    """
    if instance.status != 'COMPLETED':
        return
    if created:
        return  # Una transferencia no nace como COMPLETED

    _schedule(
        module   = 'inventory',
        action   = 'update',
        instance = instance,
        metadata = {
            'transfer_number': instance.transfer_number,
            'currency':        instance.currency.code if instance.currency_id else None,
            'status':          instance.status,
        },
    )


# ── 10 — Comparación de snapshots consecutivos ───────────────────────────────

@receiver(post_save, sender=SystemSnapshot)
def on_snapshot_created(sender, instance, created, **kwargs):
    """
    Después de cada nuevo snapshot, compara con el anterior del mismo
    módulo/sucursal usando AlertEngine y persiste cualquier anomalía en AlertLog.

    Fire-and-forget: fallos en el análisis no interrumpen el flujo principal.
    """
    if not created:
        return  # Snapshots son append-only; updates no deberían ocurrir

    def _compare():
        try:
            # Obtener snapshot anterior del mismo módulo/branch
            prev = (
                SystemSnapshot.objects
                .filter(
                    module=instance.module,
                    branch=instance.branch,
                    id__lt=instance.id,          # estrictamente anterior
                )
                .order_by('-timestamp')
                .first()
            )
            if prev is None:
                return  # Sin baseline — nada que comparar

            from .alerts import AlertEngine
            from alerts.services import GlobalAlertService

            engine = AlertEngine(
                data1 = prev.data_json,
                data2 = instance.data_json,
                snap1 = prev,
                snap2 = instance,
            )
            detected = engine.run()

            for snap_alert in detected:
                GlobalAlertService.from_snapshot_alert(
                    snap_alert = snap_alert,
                    branch     = instance.branch,
                )

            if detected:
                log.info(
                    'SNAPSHOT_COMPARE module=%s alerts=%d (snap_prev=%s → snap_new=%s)',
                    instance.module, len(detected), prev.id, instance.id,
                )
        except Exception as exc:
            log.error(
                'SNAPSHOT_COMPARE_FAIL snap=%s err=%s', instance.id, exc, exc_info=True,
            )

    # Ejecutar dentro de on_commit para asegurar que ambos snapshots estén
    # persistidos antes de la comparación.
    from django.db import transaction
    transaction.on_commit(_compare)
