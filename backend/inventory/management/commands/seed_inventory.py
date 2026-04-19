from django.core.management.base import BaseCommand
from django.utils import timezone
from decimal import Decimal
import random
from datetime import timedelta

from inventory.models import CurrencyInventory, InventoryMovement, InventoryTransfer
from users.models import User, Branch


class Command(BaseCommand):
    help = 'Seed inventory movements and transfers with realistic data'

    def handle(self, *args, **options):
        inventories = list(CurrencyInventory.objects.select_related('currency', 'branch').all())
        if not inventories:
            self.stdout.write(self.style.ERROR('No hay inventarios. Ejecuta seed_kapitalya.py primero.'))
            return

        admin = User.objects.filter(role='ADMIN').first()
        if not admin:
            self.stdout.write(self.style.ERROR('No se encontró usuario ADMIN.'))
            return

        branches = list(Branch.objects.all())

        # ── Movimientos ──────────────────────────────────────────────────────────
        movement_count = 0
        MOVEMENT_SCENARIOS = [
            ('IN',          'Compra de divisa al cliente'),
            ('OUT',         'Venta de divisa al cliente'),
            ('IN',          'Reposición de caja'),
            ('ADJUSTMENT',  'Conteo físico — ajuste menor'),
            ('OUT',         'Venta de divisa al cliente'),
            ('IN',          'Compra de divisa al cliente'),
            ('TRANSFER_IN', 'Transferencia recibida de sucursal'),
            ('OUT',         'Venta de divisa al cliente'),
        ]

        for inv in inventories:
            balance = inv.physical_balance
            wac = inv.weighted_average_cost or Decimal('7.0000')

            for i, (mtype, note) in enumerate(MOVEMENT_SCENARIOS):
                days_ago = random.randint(1, 60)
                hours_ago = random.randint(0, 23)
                amount = Decimal(str(round(random.uniform(100, min(float(balance or 5000), 5000)), 2)))
                rate = wac + Decimal(str(round(random.uniform(-0.05, 0.05), 4)))

                if mtype in ('OUT', 'TRANSFER_OUT'):
                    if balance <= Decimal('0'):
                        continue
                    amount = min(amount, balance * Decimal('0.3'))
                    if amount <= 0:
                        continue

                balance_before = balance
                if mtype in ('IN', 'TRANSFER_IN'):
                    balance += amount
                elif mtype in ('OUT', 'TRANSFER_OUT'):
                    balance = max(Decimal('0'), balance - amount)
                else:  # ADJUSTMENT
                    balance = amount

                ts = timezone.now() - timedelta(days=days_ago, hours=hours_ago)
                InventoryMovement.objects.create(
                    inventory=inv,
                    movement_type=mtype,
                    amount=amount,
                    rate=rate,
                    balance_before=balance_before,
                    balance_after=balance,
                    user=admin,
                    notes=note,
                    reference=f'REF-{inv.currency.code}-{i+1:04d}',
                    created_at=ts,
                )
                movement_count += 1

        self.stdout.write(self.style.SUCCESS(f'Creados {movement_count} movimientos'))

        # ── Transferencias ───────────────────────────────────────────────────────
        transfer_count = 0
        if len(branches) < 2:
            self.stdout.write(self.style.WARNING('Menos de 2 sucursales — se omiten transferencias'))
        else:
            statuses = ['PENDING', 'IN_TRANSIT', 'COMPLETED', 'COMPLETED', 'PENDING']
            for inv in inventories[:8]:
                other = [b for b in branches if b.id != inv.branch_id]
                if not other:
                    continue
                target = random.choice(other)
                st = random.choice(statuses)
                amount = Decimal(str(round(random.uniform(500, 3000), 2)))
                wac = inv.weighted_average_cost or Decimal('7.0000')

                auth_at = timezone.now() - timedelta(days=2) if st in ('IN_TRANSIT', 'COMPLETED') else None
                done_at = timezone.now() - timedelta(days=1) if st == 'COMPLETED' else None

                InventoryTransfer.objects.create(
                    currency=inv.currency,
                    source_branch=inv.branch,
                    target_branch=target,
                    amount=amount,
                    rate=wac,
                    status=st,
                    requested_by=admin,
                    authorized_by=admin if st in ('IN_TRANSIT', 'COMPLETED') else None,
                    authorized_at=auth_at,
                    completed_at=done_at,
                    notes='Transferencia generada por seed',
                )
                transfer_count += 1

        self.stdout.write(self.style.SUCCESS(f'Creadas {transfer_count} transferencias'))
        self.stdout.write(self.style.SUCCESS('Seed de inventario completado.'))
