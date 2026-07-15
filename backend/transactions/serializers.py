# transactions/serializers.py
from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import Transaction, Customer, TransactionDocument
from .validators import DENOMINATION_CHOICES, validate_transaction_amounts
from rates.models import Currency
from users.serializers import UserSerializer, BranchSerializer
from rates.serializers import CurrencySerializer


class StrictIntegerField(serializers.IntegerField):
    """
    IntegerField que rechaza explícitamente valores float con parte fraccionaria.
    Accepts: 100, "100", 100.0 (float sin decimales → se castea a int).
    Rejects: 100.5, "100.5" → ValidationError con mensaje en español.
    """
    def to_internal_value(self, data):
        # Reject floats that carry a fractional part BEFORE the base conversion.
        if isinstance(data, float) and data != int(data):
            raise serializers.ValidationError(
                'Solo se permiten números enteros (sin decimales). '
                f'Recibido: {data}. Ejemplo correcto: {int(data)}'
            )
        value = super().to_internal_value(data)
        return value


class CustomerSerializer(serializers.ModelSerializer):
    transaction_count = serializers.SerializerMethodField()
    total_volume      = serializers.SerializerMethodField()

    class Meta:
        model  = Customer
        fields = [
            'id', 'document_type', 'document_number', 'full_name',
            'phone', 'email', 'address', 'birth_date', 'nationality',
            'is_pep', 'is_frequent', 'notes',
            'transaction_count', 'total_volume',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_transaction_count(self, obj):
        # Uses annotated value from CustomerViewSet.get_queryset() to avoid N+1.
        # Falls back to the @property only when obj comes from a non-annotated context
        # (e.g. the inline CustomerSerializer nested inside TransactionSerializer).
        return getattr(obj, 'tx_count', None) if hasattr(obj, 'tx_count') else obj.transaction_count

    def get_total_volume(self, obj):
        if hasattr(obj, 'tx_volume'):
            return float(obj.tx_volume) if obj.tx_volume else 0.0
        return float(obj.total_volume) if obj.total_volume else 0.0

class TransactionDocumentSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.StringRelatedField()

    class Meta:
        model  = TransactionDocument
        fields = ['id', 'document_type', 'file', 'description',
                  'uploaded_by', 'uploaded_at']
        read_only_fields = ['uploaded_at']

class TransactionSerializer(serializers.ModelSerializer):
    customer      = CustomerSerializer(read_only=True)
    currency_from = CurrencySerializer(read_only=True)
    currency_to   = CurrencySerializer(read_only=True)
    cashier       = UserSerializer(read_only=True)
    supervisor    = UserSerializer(read_only=True)
    branch        = BranchSerializer(read_only=True)
    documents     = TransactionDocumentSerializer(many=True, read_only=True)
    profit_margin       = serializers.DecimalField(
        max_digits=15, decimal_places=2, read_only=True)
    requires_supervisor = serializers.BooleanField(read_only=True)
    # Impacto neto en el efectivo BOB de la empresa:
    #   BUY  → negativo (empresa paga BOB)
    #   SELL → positivo (empresa recibe BOB)
    bob_impact = serializers.SerializerMethodField(
        help_text='Impacto neto sobre el efectivo BOB: "-930.00" o "+950.00"'
    )
    # Campos de categoría regulatoria — formato de salida estandarizado
    tipo         = serializers.SerializerMethodField(help_text='"INTERNA" o "REPORTABLE"')
    reportable   = serializers.SerializerMethodField(help_text='true si se envía a ASFI')

    class Meta:
        model  = Transaction
        fields = [
            'id', 'transaction_number', 'transaction_type', 'transaction_category',
            'status',
            # ── Datos de cliente (FK + campos planos desnormalizados) ────────
            'customer', 'nombre_cliente', 'carnet_identidad',
            # ── Divisas y montos ─────────────────────────────────────────────
            'currency_from', 'currency_to',
            'amount_from', 'amount_to', 'exchange_rate',
            'payment_method', 'payment_reference', 'denomination_type',
            # ── Flags regulatorios ───────────────────────────────────────────
            'visible_asfi', 'is_reportable_to_asfi',
            # ── Personal y sucursal ──────────────────────────────────────────
            'cashier', 'supervisor', 'branch',
            'notes', 'receipt_number',
            # ── Campos calculados ────────────────────────────────────────────
            'profit_margin', 'requires_supervisor', 'bob_impact',
            'tipo', 'reportable',
            'documents',
            'created_at', 'updated_at', 'completed_at',
        ]
        read_only_fields = [
            'transaction_number', 'visible_asfi', 'is_reportable_to_asfi',
            'nombre_cliente', 'carnet_identidad',
            'created_at', 'updated_at', 'completed_at',
        ]

    def get_bob_impact(self, obj) -> str:
        """
        Retorna el impacto BOB con signo.
        BUY:  empresa paga BOB → negativo  ('-930.00')
        SELL: empresa recibe BOB → positivo ('+950.00')
        Reversed/Cancelled: prefijo 'REVERTIDA' o 'CANCELADA'.
        """
        try:
            from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
            if obj.amount_to is None:
                return '0.00'
            amount = Decimal(str(obj.amount_to)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            if obj.transaction_type == 'BUY':
                base = f"-{amount}"
            else:
                base = f"+{amount}"

            if obj.status in ('REVERSED', 'CANCELLED'):
                return f"[{obj.status}] {base}"
            return base
        except Exception:
            return '0.00'

    def get_tipo(self, obj) -> str:
        return obj.transaction_category

    def get_reportable(self, obj) -> bool:
        return obj.visible_asfi

class TransactionCreateSerializer(serializers.Serializer):
    transaction_type     = serializers.ChoiceField(choices=['BUY', 'SELL'])
    transaction_category = serializers.ChoiceField(
        choices=['REPORTABLE', 'INTERNA'],
        default='REPORTABLE',
        help_text=(
            'REPORTABLE: requiere CI del cliente, se incluye en reportes ASFI. '
            'INTERNA: sin datos de cliente obligatorios, no se reporta a ASFI.'
        ),
    )
    # ── Datos de cliente — tres formas de proveerlos ─────────────────────────
    # 1. customer dict/id  → crea o busca Customer, auto-popula nombre/CI
    # 2. nombre_cliente + carnet_identidad  → captura plana, no crea Customer
    # 3. nada → solo válido para INTERNA
    customer = serializers.JSONField(
        required=False,
        allow_null=True,
        default=None,
        help_text='Requerido para REPORTABLE (opción A). Null permitido para INTERNA.',
    )
    nombre_cliente = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
        help_text='Nombre del cliente. Para INTERNA, campo libre opcional.',
    )
    carnet_identidad = serializers.CharField(
        max_length=30,
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
        help_text=(
            'CI o número de documento. '
            'Para REPORTABLE: requerido si no se provee customer dict. '
            'Para INTERNA: opcional.'
        ),
    )
    currency_from     = serializers.CharField(max_length=10)
    currency_to       = serializers.CharField(max_length=10, default='BOB')
    amount_from       = StrictIntegerField(min_value=1)
    amount_to         = StrictIntegerField(min_value=1)
    exchange_rate     = serializers.DecimalField(max_digits=10, decimal_places=4)
    payment_method    = serializers.ChoiceField(
        choices=['CASH', 'TRANSFER', 'QR', 'CHECK', 'CARD']
    )
    denomination_type = serializers.ChoiceField(
        choices=[c[0] for c in DENOMINATION_CHOICES],
        required=False,
        allow_null=True,
        default=None,
        help_text='Requerido para CASH + USD: BILLS, SUELTOS o SINGLES.',
    )
    payment_reference = serializers.CharField(required=False, allow_blank=True, default='')
    notes             = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_currency_from(self, value):
        try:
            return Currency.objects.get(code=value)
        except Currency.DoesNotExist:
            codes = list(Currency.objects.values_list('code', flat=True))
            raise serializers.ValidationError(
                f"Divisa '{value}' no existe. Disponibles: {codes}"
            )

    def validate_currency_to(self, value):
        try:
            return Currency.objects.get(code=value)
        except Currency.DoesNotExist:
            codes = list(Currency.objects.values_list('code', flat=True))
            raise serializers.ValidationError(
                f"Divisa '{value}' no existe. Disponibles: {codes}"
            )

    def _resolve_customer(self, value) -> Customer:
        """
        Crea o busca un cliente a partir del dict recibido.
        Siempre acotado a la empresa del usuario autenticado: sin ese filtro,
        un `id` de otra empresa filtraba su PII (CI/nombre) en la respuesta, y
        el mismo documento en dos empresas rompía el get_or_create.
        """
        if not isinstance(value, dict):
            raise serializers.ValidationError("customer debe ser un objeto JSON.")

        request = self.context.get('request')
        company_id = getattr(getattr(request, 'user', None), 'company_id', None)

        if 'id' in value:
            try:
                return Customer.objects.get(pk=int(value['id']), company_id=company_id)
            except (Customer.DoesNotExist, ValueError):
                raise serializers.ValidationError(
                    f"Cliente con id={value['id']} no encontrado."
                )

        doc  = value.get('document_number', '').strip()
        name = value.get('full_name', '').strip()

        if not doc:
            raise serializers.ValidationError("document_number requerido.")
        if not name:
            raise serializers.ValidationError("full_name requerido.")

        customer, _ = Customer.objects.get_or_create(
            company_id=company_id,
            document_number=doc,
            defaults={
                'document_type': value.get('document_type', 'CI'),
                'full_name':     name,
                'phone':         value.get('phone', ''),
                'email':         value.get('email', ''),
                'nationality':   value.get('nationality', 'Boliviana'),
                'is_pep':        bool(value.get('is_pep', False)),
            }
        )
        return customer

    def validate(self, data):
        # ── Seguridad: visible_asfi es campo derivado — nunca aceptar desde input ──
        if 'visible_asfi' in self.initial_data or 'is_reportable_to_asfi' in self.initial_data:
            raise serializers.ValidationError({
                'visible_asfi': (
                    'El campo visible_asfi no puede ser establecido manualmente. '
                    'Se deriva automáticamente de transaction_category.'
                )
            })

        # ── Auto-completar denomination_type para USD CASH ────────────────────
        # Si no se envía, default inteligente para no rechazar con 400 críptico.
        currency_from_val = data.get('currency_from')
        payment_method_val = data.get('payment_method', '')
        involves_usd = (
            (hasattr(currency_from_val, 'code') and currency_from_val.code == 'USD') or
            data.get('currency_to') and hasattr(data.get('currency_to'), 'code') and
            data.get('currency_to').code == 'USD'
        )
        if (
            payment_method_val == 'CASH' and
            involves_usd and
            data.get('denomination_type') is None
        ):
            data['denomination_type'] = 'BILLS'  # default seguro: billetes grandes

        # min_value=1 on StrictIntegerField handles amount_from/amount_to > 0.
        if data['exchange_rate'] <= 0:
            raise serializers.ValidationError({'exchange_rate': 'Debe ser mayor a 0.'})

        # ── Consistencia servidor: amount_to debe derivar de amount_from × rate ──
        # El total lo calcula el cliente (float en JS); aquí se exige que cuadre
        # con la tasa declarada (±1 BOB por redondeo a entero). Sin este check,
        # un cliente manipulado podía registrar cualquier total. Solo aplica al
        # flujo estándar divisa→BOB (invariante: currency_to es siempre BOB).
        _cur_to = data.get('currency_to')
        if getattr(_cur_to, 'code', None) == 'BOB':
            from decimal import Decimal as _D
            _esperado = _D(data['amount_from']) * data['exchange_rate']
            if abs(_D(data['amount_to']) - _esperado) > _D('1'):
                raise serializers.ValidationError({
                    'amount_to': (
                        f'Inconsistente con amount_from × exchange_rate '
                        f'(esperado ≈ {_esperado:.2f}, recibido {data["amount_to"]}).'
                    )
                })

        # ── Validar tasa contra tasa primaria del sistema (tolerancia 3%) ──────
        cur_from = data.get('currency_from')
        if cur_from and hasattr(cur_from, 'code') and cur_from.code != 'BOB':
            try:
                from rates.exchange_rate_service import ExchangeRateService
                svc = ExchangeRateService()
                is_valid, msg = svc.validate_transaction_rate(
                    cur_from.code, data['exchange_rate'], tolerance_pct=3.0
                )
                if not is_valid:
                    raise serializers.ValidationError({'exchange_rate': msg})
            except serializers.ValidationError:
                raise
            except Exception:
                pass  # Never block a transaction due to validation service failure

        category     = data.get('transaction_category', 'REPORTABLE')
        raw_customer = data.get('customer')
        ci_directo   = (data.get('carnet_identidad') or '').strip()
        nombre_dir   = (data.get('nombre_cliente')   or '').strip()

        # ── Resolución de cliente según categoría ────────────────────────────
        if category == 'REPORTABLE':
            if raw_customer:
                # Opción A: customer dict → resolver FK, auto-pobla CI/nombre
                try:
                    data['customer'] = self._resolve_customer(raw_customer)
                except serializers.ValidationError as exc:
                    raise serializers.ValidationError({'customer': exc.detail})
                # Poblar campos planos desde el customer resuelto
                if not ci_directo:
                    data['carnet_identidad'] = data['customer'].document_number
                if not nombre_dir:
                    data['nombre_cliente'] = data['customer'].full_name

            elif ci_directo:
                # Opción B: solo CI directo — válido para REPORTABLE sin Customer FK
                # El campo carnet_identidad ya está en data
                data['customer'] = None

            else:
                # Sin customer ni CI directo → error claro
                raise serializers.ValidationError({
                    'carnet_identidad': (
                        'CI requerido para transacciones reportables. '
                        'Provea customer dict o el campo carnet_identidad.'
                    )
                })

        else:
            # INTERNA — cliente y CI completamente opcionales
            if raw_customer:
                try:
                    data['customer'] = self._resolve_customer(raw_customer)
                except serializers.ValidationError as exc:
                    raise serializers.ValidationError({'customer': exc.detail})
                if not ci_directo:
                    data['carnet_identidad'] = data['customer'].document_number
                if not nombre_dir:
                    data['nombre_cliente'] = data['customer'].full_name
            else:
                data['customer'] = None

        # ── Validación financiera de denominación y montos enteros ──────────
        currency_from = data.get('currency_from')
        currency_to   = data.get('currency_to')
        if currency_from and currency_to:
            try:
                validate_transaction_amounts(
                    currency_from_code=currency_from.code,
                    currency_to_code=currency_to.code,
                    amount_from=data['amount_from'],
                    amount_to=data['amount_to'],
                    payment_method=data.get('payment_method', ''),
                    denomination_type=data.get('denomination_type'),
                    transaction_type=data.get('transaction_type', 'BUY'),
                )
            except DjangoValidationError as exc:
                # message_dict existe solo si se levantó con un dict;
                # message_list / messages cubren el caso de lista/string.
                try:
                    raise serializers.ValidationError(exc.message_dict)
                except AttributeError:
                    raise serializers.ValidationError(
                        {'non_field_errors': exc.messages}
                    )

        return data