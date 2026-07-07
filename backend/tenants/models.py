from django.db import models
from django.utils.text import slugify


class Company(models.Model):
    """Top-level tenant. Every piece of financial data belongs to one company."""

    COUNTRY_CHOICES = [
        ('BO', 'Bolivia'),
        ('PE', 'Perú'),
        ('AR', 'Argentina'),
        ('CL', 'Chile'),
        ('BR', 'Brasil'),
        ('CO', 'Colombia'),
        ('PY', 'Paraguay'),
        ('UY', 'Uruguay'),
        ('OTHER', 'Otro'),
    ]

    name          = models.CharField(max_length=200, verbose_name='Razón social')
    slug          = models.SlugField(max_length=80, unique=True, help_text='Identificador URL-friendly')
    tax_id        = models.CharField(max_length=50, blank=True, verbose_name='NIT / RUT / CUIT')
    country       = models.CharField(max_length=10, choices=COUNTRY_CHOICES, default='BO')
    base_currency = models.CharField(max_length=10, default='BOB', verbose_name='Moneda base')
    logo_url      = models.URLField(blank=True)
    is_active     = models.BooleanField(default=True, db_index=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Empresa'
        verbose_name_plural = 'Empresas'
        ordering            = ['name']

    def save(self, *args, **kwargs):
        # Autogenerar slug desde name; sufijo numérico si ya existe (unique).
        if not self.slug:
            base = slugify(self.name)[:70] or 'empresa'
            slug = base
            n = 2
            while Company.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Subscription(models.Model):
    """SaaS billing plan per company. Enforces feature/volume limits."""

    PLAN_CHOICES = [
        ('FREE',       'Gratuito'),
        ('STARTER',    'Starter'),
        ('GROWTH',     'Growth'),
        ('ENTERPRISE', 'Enterprise'),
    ]

    company      = models.OneToOneField(Company, on_delete=models.CASCADE, related_name='subscription')
    plan         = models.CharField(max_length=20, choices=PLAN_CHOICES, default='FREE')
    is_active    = models.BooleanField(default=True)
    trial_ends   = models.DateTimeField(null=True, blank=True)
    # Hard limits enforced at API level
    max_branches         = models.IntegerField(default=1)
    max_users            = models.IntegerField(default=5)
    max_transactions_mo  = models.IntegerField(default=500, help_text='Transactions per month')
    # Billing
    billing_email        = models.EmailField(blank=True)
    next_billing_date    = models.DateField(null=True, blank=True)
    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Suscripción'
        verbose_name_plural = 'Suscripciones'

    def __str__(self):
        return f"{self.company.name} — {self.plan}"

    @property
    def is_in_trial(self):
        from django.utils import timezone
        return bool(self.trial_ends and timezone.now() < self.trial_ends)
