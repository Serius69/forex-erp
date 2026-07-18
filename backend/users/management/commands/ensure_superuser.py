"""
ensure_superuser — garantiza de forma IDEMPOTENTE el superuser maestro (sergio).

Regla (misma que en el ecosistema): al finalizar cualquier deploy/ronda se asegura
que el superuser exista y pueda entrar como ADMIN. Si YA existe, **NUNCA** se resetea
su contraseña — solo se reparan los flags de privilegio (is_superuser/is_staff/
is_active/role) por si quedaron degradados. Si NO existe, se crea con la contraseña
tomada de entorno (FOREX_SUPERUSER_PASSWORD / DJANGO_SUPERUSER_PASSWORD) o el default
conocido del seed.

A diferencia de los seeders (seed_data / seed_kapitalya), este comando es seguro de
correr en producción en cada deploy: no pisa la contraseña del dueño ni siembra datos.

Uso:
    python manage.py ensure_superuser
    python manage.py ensure_superuser --username sergio --email kapitalyabolivia@gmail.com
"""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

DEFAULT_USERNAME = 'sergio'
DEFAULT_EMAIL    = 'kapitalyabolivia@gmail.com'
DEFAULT_PASSWORD = 'Kapitalya2026!'   # solo se usa al CREAR; nunca al actualizar


class Command(BaseCommand):
    help = 'Asegura idempotente el superuser maestro (crea si falta; NO resetea password si existe).'

    def add_arguments(self, parser):
        parser.add_argument('--username', default=DEFAULT_USERNAME)
        parser.add_argument('--email',    default=DEFAULT_EMAIL)

    def handle(self, *args, **opts):
        User = get_user_model()
        username = opts['username']
        email    = opts['email']

        # Sucursal/empresa principal si existen (opcional; no falla en DB vacía).
        branch = None
        company = None
        try:
            from users.models import Branch
            branch = (Branch.objects.filter(is_main=True).first()
                      or Branch.objects.order_by('id').first())
            company = getattr(branch, 'company', None)
        except Exception:  # noqa: BLE001 — Branch puede no existir aún en un DB fresco
            pass

        user = User.objects.filter(username=username).first()

        if user is None:
            password = (os.environ.get('FOREX_SUPERUSER_PASSWORD')
                        or os.environ.get('DJANGO_SUPERUSER_PASSWORD')
                        or DEFAULT_PASSWORD)
            extra = {'first_name': 'Sergio', 'last_name': 'Troche', 'role': 'ADMIN'}
            if branch is not None:
                extra['branch'] = branch
            if company is not None:
                extra['company'] = company
            User.objects.create_superuser(
                username=username, email=email, password=password, **extra,
            )
            self.stdout.write(self.style.SUCCESS(
                f'✓ superuser «{username}» creado (ADMIN).'))
            return

        # Ya existe: reparar SOLO flags de privilegio, jamás la contraseña.
        changed = []
        if not user.is_superuser:
            user.is_superuser = True; changed.append('is_superuser')
        if not user.is_staff:
            user.is_staff = True; changed.append('is_staff')
        if not user.is_active:
            user.is_active = True; changed.append('is_active')
        if getattr(user, 'role', None) != 'ADMIN':
            user.role = 'ADMIN'; changed.append('role')

        if changed:
            user.save(update_fields=changed)
            self.stdout.write(self.style.WARNING(
                f'✓ superuser «{username}» ya existía — flags reparados: '
                f'{", ".join(changed)} (password intacto).'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'✓ superuser «{username}» ya existía y está correcto (sin cambios).'))
