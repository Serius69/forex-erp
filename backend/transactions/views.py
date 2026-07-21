# transactions/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from datetime import datetime, timedelta, time
from django.utils.dateparse import parse_date
from django.http import HttpResponse
from .models import Transaction, Customer, TransactionDocument
from .serializers import (
    TransactionSerializer, TransactionListSerializer, CustomerSerializer,
    TransactionCreateSerializer, TransactionDocumentSerializer
)
from django.db import transaction as db_transaction
from .services import TransactionService
from .permissions import CanReverseTransaction
from core.ratelimit import rate_limit
from core.pagination import TransactionCursorPagination
from tenants.permissions import IsCompanyMember

class TransactionViewSet(viewsets.ModelViewSet):
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated, IsCompanyMember]
    pagination_class = TransactionCursorPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        # ── Tenant isolation: always scope to user's company ─────────────────
        if getattr(user, 'company_id', None):
            queryset = queryset.filter(branch__company_id=user.company_id)

        # ── Branch isolation: CASHIER only sees own branch ───────────────────
        if user.role == 'CASHIER' and user.branch_id:
            queryset = queryset.filter(branch_id=user.branch_id)
        elif not user.has_perm('transactions.can_view_all_branches') and user.role not in ('ADMIN', 'SUPERVISOR'):
            queryset = queryset.filter(branch=user.branch)
        
        # Filtros adicionales
        customer_id = self.request.query_params.get('customer_id')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        tx_status = self.request.query_params.get('status')
        transaction_type = (
            self.request.query_params.get('transaction_type') or
            self.request.query_params.get('type')
        )
        
        # ?asfi=true/false  OR  ?reportable=true/false  (alias, both supported)
        asfi_param       = self.request.query_params.get('asfi')
        reportable_param = self.request.query_params.get('reportable')
        _flag = asfi_param if asfi_param is not None else reportable_param
        if _flag == 'true':
            queryset = queryset.filter(visible_asfi=True)
        elif _flag == 'false':
            queryset = queryset.filter(visible_asfi=False)

        # ?category=REPORTABLE|INTERNA  — filtrar por categoría exacta
        category_param = self.request.query_params.get('category')
        if category_param in ('REPORTABLE', 'INTERNA'):
            queryset = queryset.filter(transaction_category=category_param)

        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        # Filtro de fecha SARGABLE: se convierte el rango de días locales
        # (America/La_Paz) a límites datetime absolutos para que el índice btree
        # sobre -created_at haga seek en vez de un DATE(created_at AT TIME ZONE ...)
        # no sargable (full scan). Rango [inicio de date_from local, inicio del día
        # siguiente a date_to local) — mismos días que __date__gte/__lte inclusivos.
        tz_local = timezone.get_current_timezone()
        if date_from:
            d = parse_date(str(date_from))
            if d:
                queryset = queryset.filter(
                    created_at__gte=timezone.make_aware(datetime.combine(d, time.min), tz_local)
                )
        if date_to:
            d = parse_date(str(date_to))
            if d:
                queryset = queryset.filter(
                    created_at__lt=timezone.make_aware(
                        datetime.combine(d + timedelta(days=1), time.min), tz_local
                    )
                )
        if tx_status:
            queryset = queryset.filter(status=tx_status)
        if transaction_type:
            queryset = queryset.filter(transaction_type=transaction_type)
        
        # select_related profundo: los serializers anidados de cashier/supervisor
        # (UserSerializer) recorren .branch → .company (company_name) y .company;
        # sin traerlos aquí, cada fila disparaba ~3 queries EXTRA (N+1).
        return queryset.select_related(
            'customer', 'currency_from', 'currency_to',
            'branch', 'branch__company',
            'cashier', 'cashier__branch', 'cashier__branch__company', 'cashier__company',
            'supervisor', 'supervisor__branch', 'supervisor__branch__company', 'supervisor__company',
        ).prefetch_related('documents').order_by('-created_at')
    
    def list(self, request, *args, **kwargs):
        """Override to return structured JSON on DB/serialization errors."""
        try:
            return super().list(request, *args, **kwargs)
        except Exception as exc:
            import logging as _log
            # Se registra el traceback completo para diagnóstico, pero NO se
            # expone el detalle interno (str(exc)) al cliente en el 500.
            _log.getLogger('transactions').exception('TX_LIST_FAILED err=%s', exc)
            return Response(
                {'error': 'Error al obtener transacciones'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def get_serializer_class(self):
        if self.action == 'create':
            return TransactionCreateSerializer
        if self.action == 'list':
            # Serializer ligero sin profit_margin (evita N+1 al paginar).
            return TransactionListSerializer
        return TransactionSerializer

    @rate_limit(requests=60, window=60, scope='user')
    def create(self, request):
        serializer = TransactionCreateSerializer(
            data=request.data,
            context={'request': request}
        )
        if not serializer.is_valid():
            # Formato estandarizado: `field_errors` + `message` legible
            first_msgs = []
            for field, errs in serializer.errors.items():
                if isinstance(errs, list):
                    first_msgs.append(f"{field}: {errs[0]}")
                elif isinstance(errs, dict):
                    for sub_field, sub_errs in errs.items():
                        first_msgs.append(f"{field}.{sub_field}: {sub_errs[0] if sub_errs else errs}")
            return Response(
                {
                    'code':         'VALIDATION_ERROR',
                    'message':      ' | '.join(first_msgs[:3]),
                    'field_errors': serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        vd       = serializer.validated_data
        customer = vd['customer']
        cur_from = vd['currency_from']
        cur_to   = vd['currency_to']
        branch   = request.user.branch

        if not branch:
            return Response(
                {'error': 'Usuario sin sucursal asignada'},
                status=status.HTTP_400_BAD_REQUEST
            )

        import logging
        log = logging.getLogger('transactions')

        # ── Idempotency key — prevenir transacciones duplicadas ───────────────
        idempotency_key = request.META.get('HTTP_IDEMPOTENCY_KEY', '').strip()
        if idempotency_key:
            from django.core.cache import cache
            idem_cache_key = f"tx_idem:{request.user.id}:{idempotency_key}"
            existing_tx_id = cache.get(idem_cache_key)
            if existing_tx_id:
                try:
                    existing_tx = Transaction.objects.get(pk=existing_tx_id)
                    log.info(
                        "IDEMPOTENCY_HIT key=%s tx=%s",
                        idempotency_key, existing_tx.transaction_number,
                    )
                    return Response(
                        TransactionSerializer(existing_tx).data,
                        status=status.HTTP_200_OK,
                    )
                except Transaction.DoesNotExist:
                    pass  # La TX fue eliminada; continuar creando una nueva

        # ── Validación de monto máximo: requiere PIN de supervisor ────────────
        # Reglas de negocio (BUSINESS_LOGIC.md §10):
        #   USD > 5,000 | BOB > 35,000 | otras > 35,000 BOB equivalente
        amount_from   = vd['amount_from']
        exchange_rate = vd['exchange_rate']

        def _requires_supervisor_check():
            # Umbrales centralizados en el modelo (fuente única)
            usd_max = Transaction.SUPERVISOR_THRESHOLD_USD
            bob_max = Transaction.SUPERVISOR_THRESHOLD_BOB
            if cur_from.code == 'USD':
                return amount_from > usd_max
            if cur_from.code == 'BOB':
                return amount_from > bob_max
            return amount_from * exchange_rate > bob_max

        supervisor_instance = None
        if _requires_supervisor_check():
            raw_pin = request.META.get('HTTP_X_SUPERVISOR_PIN', '').strip()
            if not raw_pin:
                log.warning(
                    "SUPERVISOR_REQUIRED cashier=%s amount=%s %s",
                    request.user.username, amount_from, cur_from.code,
                )
                return Response(
                    {
                        'error':  'Requiere supervisor',
                        'detail': (
                            f'Transacciones de {cur_from.code} '
                            f'superiores al límite requieren '
                            f'autorización de supervisor. '
                            f'Envía el header X-Supervisor-PIN con el PIN.'
                        ),
                        'code':   'SUPERVISOR_REQUIRED',
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Validar PIN contra los supervisores/admins DE LA MISMA EMPRESA.
            # Sin el filtro por company, el PIN podía coincidir con un supervisor
            # de otra empresa → aprobación cross-tenant y aprobador ajeno en la
            # auditoría/RTE ASFI. La granularidad correcta es company (no branch:
            # un ADMIN suele tener branch=None y aprueba en varias sucursales).
            from users.models import User as UserModel
            for sup in UserModel.objects.filter(
                role__in=('ADMIN', 'SUPERVISOR'),
                company_id=request.user.company_id,
            ):
                if sup.check_pin(raw_pin):
                    supervisor_instance = sup
                    break

            if supervisor_instance is None:
                log.warning(
                    "INVALID_SUPERVISOR_PIN cashier=%s amount=%s %s",
                    request.user.username, amount_from, cur_from.code,
                )
                return Response(
                    {'error': 'PIN inválido', 'code': 'INVALID_PIN'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            log.info(
                "SUPERVISOR_APPROVED tx_by=%s supervisor=%s amount=%s %s",
                request.user.username, supervisor_instance.username,
                amount_from, cur_from.code,
            )

        try:
            with db_transaction.atomic():
                # Lock del branch para serializar la generación del número.
                # Previene race condition entre cajeros concurrentes.
                from users.models import Branch as BranchModel
                BranchModel.objects.select_for_update().get(pk=branch.pk)

                now    = timezone.now()
                prefix = f"{branch.code}{now.strftime('%Y%m%d')}"
                last   = Transaction.objects.filter(
                    transaction_number__startswith=prefix
                ).order_by('-transaction_number').select_for_update().first()
                seq    = int(last.transaction_number[-4:]) + 1 if last else 1
                tx_num = f"{prefix}{seq:04d}"

                # ── Motor antifraude (reglas HIGH_VALUE/RATE_SANITY/VELOCITY…) ──
                # Antes el motor existía pero NUNCA se invocaba en el path real:
                # fraud_score/approval_required quedaban siempre en default.
                from .fraud_detection import BLOCK, FraudDetectionEngine
                fraud = FraudDetectionEngine().evaluate(
                    transaction_type = vd['transaction_type'],
                    currency_from    = cur_from.code,
                    currency_to      = cur_to.code,
                    amount_from      = int(vd['amount_from']),
                    amount_to        = int(vd['amount_to']),
                    exchange_rate    = vd['exchange_rate'],
                    customer         = customer,
                    cashier          = request.user,
                    branch           = branch,
                )
                if fraud.decision == BLOCK:
                    return Response(
                        {'error': 'Transacción bloqueada por el motor antifraude',
                         'fraud_flags': fraud.flags,
                         'fraud_score': str(fraud.score)},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                # REQUIRE_APPROVAL: la operación NO se completa ni mueve
                # inventario/caja hasta que un supervisor la apruebe (approve()).
                # Antes se creaba COMPLETED con efectos aplicados y approve() la
                # rechazaba por estar COMPLETED → la decisión era inefectiva.
                requires_approval = (fraud.decision == 'REQUIRE_APPROVAL')

                # Cuantizar montos con precisión financiera
                from core.finance import quantize_amount, quantize_money, quantize_rate
                tx = Transaction.objects.create(
                    transaction_number    = tx_num,
                    transaction_type      = vd['transaction_type'],
                    transaction_category  = vd.get('transaction_category', 'REPORTABLE'),
                    status                = 'PENDING' if requires_approval else 'COMPLETED',
                    customer              = customer,
                    nombre_cliente        = vd.get('nombre_cliente') or None,
                    carnet_identidad      = vd.get('carnet_identidad') or None,
                    currency_from         = cur_from,
                    currency_to           = cur_to,
                    amount_from           = quantize_amount(vd['amount_from']),
                    amount_to             = quantize_money(vd['amount_to']),
                    exchange_rate         = quantize_rate(vd['exchange_rate']),
                    payment_method        = vd['payment_method'],
                    payment_reference     = vd.get('payment_reference') or '',
                    denomination_type     = vd.get('denomination_type'),
                    notes                 = vd.get('notes') or '',
                    cashier               = request.user,
                    branch                = branch,
                    supervisor            = supervisor_instance,
                    completed_at          = None if requires_approval else now,
                    # Resultado del motor antifraude (persistido para auditoría/ML)
                    fraud_score           = fraud.score,
                    fraud_flags           = fraud.flags,
                    approval_required     = requires_approval,
                )

                # Inventario + efectos BOB: SOLO si no requiere aprobación. Las
                # que la requieren quedan PENDING sin mover inventario/caja; sus
                # efectos se aplican en approve(). NO envuelto en try/except: si
                # falla, el atomic block hace rollback completo.
                if not requires_approval:
                    service = TransactionService()
                    service._update_inventory(tx)
                    # BUY → BOB disminuye · SELL → BOB aumenta
                    from .services import apply_transaction_effects
                    apply_transaction_effects(tx)   # raises ValidationError si saldo negativo

                # Audit log — obligatorio, se registra dentro del atomic
                from users.models import UserActivity
                UserActivity.objects.create(
                    user       = request.user,
                    action     = 'TRANSACTION_CREATED',
                    details    = {
                        'tx_number':        tx.transaction_number,
                        'transaction_type': tx.transaction_type,
                        'amount_from':      str(tx.amount_from),
                        'amount_to':        str(tx.amount_to),
                        'exchange_rate':    str(tx.exchange_rate),
                        'currency_from':    tx.currency_from.code,
                        'currency_to':      tx.currency_to.code,
                        'payment_method':        tx.payment_method,
                        'transaction_category': tx.transaction_category,
                        'customer_id':           tx.customer_id,
                        'nombre_cliente':         tx.nombre_cliente,
                        'carnet_identidad':        tx.carnet_identidad,
                        'branch':                branch.code,
                        'supervisor':       supervisor_instance.username if supervisor_instance else None,
                    },
                    ip_address = self.get_client_ip(request),
                    user_agent = request.META.get('HTTP_USER_AGENT', ''),
                )

            # ── Registrar idempotency key post-commit ─────────────────────────
            # Debe ejecutarse dentro de on_commit: si el atomic block hizo rollback
            # (p.ej. ValidationError de capital), la key no debe quedar en caché.
            if idempotency_key:
                from django.core.cache import cache
                _tx_id = tx.id
                db_transaction.on_commit(
                    lambda: cache.set(idem_cache_key, _tx_id, timeout=86400)
                )

            # ── Audit log financiero ──────────────────────────────────────────
            audit = logging.getLogger('audit')
            audit.info(
                "TX_CREATED tx=%s type=%s cashier=%s branch=%s "
                "amount_from=%s %s amount_to=%s BOB rate=%s customer=%s supervisor=%s",
                tx.transaction_number, tx.transaction_type,
                request.user.username, branch.code,
                tx.amount_from, cur_from.code,
                tx.amount_to, tx.exchange_rate,
                tx.carnet_identidad or 'N/A',
                supervisor_instance.username if supervisor_instance else 'N/A',
            )
            log.info(
                "TRANSACTION_CREATED tx=%s cashier=%s amount=%s %s",
                tx.transaction_number, request.user.username,
                tx.amount_from, cur_from.code,
            )

            # ── Detección de anomalías post-commit ────────────────────────────
            try:
                from core.alerts import FinancialAnomalyDetector
                FinancialAnomalyDetector.check_large_transaction(tx)
                FinancialAnomalyDetector.record_transaction(request.user.id, branch.id)
                FinancialAnomalyDetector.check_rapid_transactions(request.user.id, branch.id)
            except Exception:
                pass  # anomaly detection nunca rompe el flujo principal

            return Response(
                TransactionSerializer(tx).data,
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            log.error(
                "TRANSACTION_CREATE_FAILED cashier=%s err=%s",
                request.user.username, e, exc_info=True,
            )
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    # ── EDIT ─────────────────────────────────────────────────────────────────
    def update(self, request, pk=None, **kwargs):
        """
        PATCH /api/transactions/{id}/ — editar notas, método de pago, referencia.
        Solo campos no-financieros; los montos/tasas son inmutables una vez completada.
        Requiere rol ADMIN o SUPERVISOR.
        """
        if request.user.role not in ('ADMIN', 'SUPERVISOR'):
            return Response(
                {'error': 'Solo administradores o supervisores pueden editar transacciones'},
                status=status.HTTP_403_FORBIDDEN,
            )

        tx = self.get_object()
        if tx.status == 'REVERSED':
            return Response(
                {'error': 'No se puede editar una transacción revertida'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        EDITABLE_FIELDS = {'notes', 'payment_method', 'payment_reference'}
        data = {k: v for k, v in request.data.items() if k in EDITABLE_FIELDS}

        if not data:
            return Response(
                {'error': f'Solo se pueden editar: {", ".join(EDITABLE_FIELDS)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        for field, value in data.items():
            setattr(tx, field, value)
        tx.save(update_fields=list(data.keys()) + ['updated_at'])

        import logging
        from users.models import UserActivity
        UserActivity.objects.create(
            user       = request.user,
            action     = 'TRANSACTION_EDITED',
            details    = {'tx_number': tx.transaction_number, 'changed': data},
            ip_address = self.get_client_ip(request),
            user_agent = request.META.get('HTTP_USER_AGENT', ''),
        )
        logging.getLogger('audit').info(
            "TX_EDITED tx=%s editor=%s fields=%s",
            tx.transaction_number, request.user.username, list(data.keys()),
        )

        return Response(TransactionSerializer(tx).data)

    partial_update = update  # PATCH delegates to update

    # ── DELETE ────────────────────────────────────────────────────────────────
    def destroy(self, request, pk=None):
        """
        DELETE /api/transactions/{id}/ — anular y restaurar inventario.
        Solo ADMIN. Marca como CANCELLED y revierte el inventario exactamente.
        No borra el registro (auditoría financiera).
        """
        if request.user.role != 'ADMIN':
            return Response(
                {'error': 'Solo administradores pueden eliminar transacciones'},
                status=status.HTTP_403_FORBIDDEN,
            )

        tx = self.get_object()
        if tx.status in ('CANCELLED', 'REVERSED'):
            return Response(
                {'error': f'La transacción ya está {tx.status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response(
                {'error': 'Debe proporcionar una razón para eliminar la transacción'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        import logging
        log = logging.getLogger('transactions')

        try:
            with db_transaction.atomic():
                service = TransactionService()
                service._reverse_inventory(tx)

                # Revertir efectos BOB (devuelve el movimiento de caja exacto)
                from .services import reverse_transaction_effects
                reverse_transaction_effects(tx)

                tx.status = 'CANCELLED'
                tx.notes  = (tx.notes + f'\n[CANCELADO por {request.user.username}: {reason}]').strip()
                tx.save(update_fields=['status', 'notes', 'updated_at'])

                from users.models import UserActivity
                UserActivity.objects.create(
                    user       = request.user,
                    action     = 'TRANSACTION_CANCELLED',
                    details    = {
                        'tx_number':        tx.transaction_number,
                        'reason':           reason,
                        'amount_from':      str(tx.amount_from),
                        'currency_from':    tx.currency_from.code,
                        'original_status':  'COMPLETED',
                    },
                    ip_address = self.get_client_ip(request),
                    user_agent = request.META.get('HTTP_USER_AGENT', ''),
                )
                logging.getLogger('audit').info(
                    "TX_CANCELLED tx=%s admin=%s reason=%s",
                    tx.transaction_number, request.user.username, reason,
                )

            return Response(
                {'success': True, 'message': f'Transacción {tx.transaction_number} cancelada. Inventario revertido.'},
                status=status.HTTP_200_OK,
            )

        except Exception as exc:
            log.error("TX_CANCEL_FAILED tx=%s err=%s", pk, exc, exc_info=True)
            return Response({'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['POST'],
        permission_classes=[CanReverseTransaction],
        url_path='reverse')
    def reverse(self, request, pk=None):
        """Revierte una transacción"""
        transaction = self.get_object()
        reason = request.data.get('reason', '')
        
        if not reason:
            return Response(
                {'error': 'Debe proporcionar una razón para la reversa'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            reversal = transaction.reverse(
                request.user, reason,
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
            )

            return Response({
                'success': True,
                'reversal': TransactionSerializer(reversal).data
            })
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['GET'], url_path='receipt')
    def receipt(self, request, pk=None):
        """Descarga el comprobante de la transacción"""
        transaction = self.get_object()
        
        try:
            document = transaction.documents.filter(
                document_type='RECEIPT'
            ).latest('uploaded_at')
            
            response = HttpResponse(
                document.file,
                content_type='application/pdf'
            )
            response['Content-Disposition'] = f'attachment; filename="{transaction.transaction_number}.pdf"'
            return response
            
        except TransactionDocument.DoesNotExist:
            # Generar nuevo comprobante
            service = TransactionService()
            receipt_file = service._generate_receipt(transaction)
            
            response = HttpResponse(receipt_file, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{transaction.transaction_number}.pdf"'
            return response
    
    @action(detail=False, methods=['GET'], url_path='daily-summary')
    def daily_summary(self, request):
        date_str = request.query_params.get('date', '')
        if date_str:
            target_date = parse_date(date_str) or timezone.localdate()
        else:
            target_date = timezone.localdate()
        
        # Límites datetime sargables (usan el índice -created_at) equivalentes a
        # created_at__date == target_date en zona local America/La_Paz.
        tz_local = timezone.get_current_timezone()
        day_start = timezone.make_aware(datetime.combine(target_date, time.min), tz_local)
        day_end = timezone.make_aware(
            datetime.combine(target_date + timedelta(days=1), time.min), tz_local
        )
        transactions = self.get_queryset().filter(
            created_at__gte=day_start, created_at__lt=day_end
        )

        # 5 consultas agrupadas en total (antes: ~50+ — un count/aggregate por
        # divisa×lado + 24 pares count/aggregate horarios → N+1 severo).
        from django.db.models import Q
        from django.db.models.functions import ExtractHour

        totals = transactions.aggregate(
            total=Count('id'),
            buy_count=Count('id', filter=Q(transaction_type='BUY')),
            sell_count=Count('id', filter=Q(transaction_type='SELL')),
            volume_bob=Sum('amount_to'),
        )

        summary = {
            'date': target_date,
            'total_transactions': totals['total'],
            'by_type': {
                'buy': totals['buy_count'],
                'sell': totals['sell_count'],
            },
            'by_currency': {},
            'total_volume_bob': totals['volume_bob'] or 0,
            'by_payment_method': {},
            'by_hour': []
        }

        # Resumen por divisa — una sola consulta agrupada
        # (order_by() limpia el ordering default, que se colaría en el GROUP BY)
        by_currency = (transactions
                       .values('currency_from__code')
                       .order_by('currency_from__code')
                       .annotate(
                           buy_count=Count('id', filter=Q(transaction_type='BUY')),
                           buy_volume=Sum('amount_from', filter=Q(transaction_type='BUY')),
                           sell_count=Count('id', filter=Q(transaction_type='SELL')),
                           sell_volume=Sum('amount_from', filter=Q(transaction_type='SELL')),
                       ))
        for row in by_currency:
            summary['by_currency'][row['currency_from__code']] = {
                'buy':  {'count': row['buy_count'],  'volume': row['buy_volume'] or 0},
                'sell': {'count': row['sell_count'], 'volume': row['sell_volume'] or 0},
            }

        # Por método de pago — una sola consulta agrupada
        payment_methods = transactions.values('payment_method').order_by('payment_method').annotate(
            count=Count('id'),
            volume=Sum('amount_to')
        )
        for pm in payment_methods:
            summary['by_payment_method'][pm['payment_method']] = {
                'count': pm['count'],
                'volume': float(pm['volume'] or 0)
            }

        # Por hora del día — una sola consulta agrupada (huecos rellenos con 0)
        by_hour = {row['hour']: row for row in (
            transactions
            .annotate(hour=ExtractHour('created_at'))
            .values('hour')
            .order_by('hour')
            .annotate(count=Count('id'), volume=Sum('amount_to'))
        )}
        for hour in range(24):
            row = by_hour.get(hour)
            summary['by_hour'].append({
                'hour': hour,
                'count': row['count'] if row else 0,
                'volume': float(row['volume'] or 0) if row else 0.0,
            })

        return Response(summary)
    
    @action(detail=False, methods=['GET'], url_path='pending-approvals')
    def pending_approvals(self, request):
        """Transacciones pendientes de aprobación"""
        if request.user.role not in ['ADMIN', 'SUPERVISOR']:
            return Response(
                {'error': 'No autorizado'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        pending = self.get_queryset().filter(
            status='PENDING',
            supervisor__isnull=True
        ).filter(
            Q(amount_from__gte=5000) | Q(amount_to__gte=35000)
        )
        
        serializer = self.get_serializer(pending, many=True)
        return Response(serializer.data)
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

    @action(detail=True, methods=['GET'], url_path='audit-trail')
    def audit_trail(self, request, pk=None):
        """
        GET /api/transactions/{id}/audit-trail/
        Historial de auditoría inmutable de la transacción.
        Solo ADMIN, SUPERVISOR o usuarios con can_view_audit_trail.
        """
        from .permissions import CanViewAuditTrail
        perm = CanViewAuditTrail()
        if not perm.has_permission(request, self):
            return Response({'error': perm.message}, status=status.HTTP_403_FORBIDDEN)

        tx = self.get_object()
        from .audit import TransactionAuditLog
        logs = (
            TransactionAuditLog.objects
            .filter(transaction=tx)
            .select_related('user')
            .order_by('-timestamp_utc')
        )
        data = [
            {
                'id':               entry.id,
                'action':           entry.action,
                'action_display':   entry.get_action_display(),
                'user':             entry.user_display or 'sistema',
                'ip_address':       entry.ip_address,
                'timestamp_utc':    entry.timestamp_utc.isoformat(),
                'previous_state':   entry.previous_state,
                'new_state':        entry.new_state,
                'checksum_ok':      entry.verify_integrity(),
            }
            for entry in logs
        ]
        return Response({
            'transaction_number': tx.transaction_number,
            'entry_count':        len(data),
            'entries':            data,
        })

    @action(detail=True, methods=['POST'], url_path='approve')
    def approve(self, request, pk=None):
        """
        POST /api/transactions/{id}/approve/
        Aprueba una transacción que requiere revisión antifraude.
        Solo ADMIN o SUPERVISOR con permiso can_approve_high_value.
        """
        from .permissions import CanApproveHighValue
        perm = CanApproveHighValue()
        if not perm.has_permission(request, self):
            return Response({'error': perm.message}, status=status.HTTP_403_FORBIDDEN)

        tx = self.get_object()
        if not tx.approval_required:
            return Response({'error': 'Esta transacción no requiere aprobación.'}, status=status.HTTP_400_BAD_REQUEST)
        if tx.status in ('COMPLETED', 'CANCELLED', 'REVERSED'):
            return Response({'error': f'No se puede aprobar una transacción en estado {tx.status}.'}, status=status.HTTP_400_BAD_REQUEST)

        from django.utils import timezone as tz
        from django.core.exceptions import ValidationError
        from .audit import create_audit_log, snapshot_transaction

        prev = snapshot_transaction(tx)
        # Al aprobar se aplican por PRIMERA vez los efectos (inventario + caja):
        # la tx se creó PENDING sin moverlos. Atómico: si el inventario/caja ya
        # no alcanzan (cambiaron desde la creación), se revierte y responde 409.
        try:
            with db_transaction.atomic():
                service = TransactionService()
                service._update_inventory(tx)
                from .services import apply_transaction_effects
                apply_transaction_effects(tx)
                tx.approval_required = False
                tx.approved_by = request.user
                tx.approved_at = tz.now()
                tx.status = 'COMPLETED'
                tx.completed_at = tz.now()
                tx.save(update_fields=[
                    'approval_required', 'approved_by', 'approved_at',
                    'status', 'completed_at', 'updated_at',
                ])
        except ValidationError as exc:
            return Response(
                {'error': 'No se pudo aprobar: inventario o caja insuficientes.',
                 'detail': exc.messages if hasattr(exc, 'messages') else str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        create_audit_log(
            transaction=tx,
            action='APPROVED',
            previous_state=prev,
            new_state=snapshot_transaction(tx),
            user=request.user,
            request=request,
        )
        from .serializers import TransactionSerializer
        return Response(TransactionSerializer(tx, context={'request': request}).data)

    @action(detail=True, methods=['GET'], url_path='risk-explanation')
    def risk_explanation(self, request, pk=None):
        """Explicabilidad SHAP del riesgo de revisión de una transacción.

        Complementa al motor de reglas (`fraud_detection`) con un modelo CatBoost que
        aprende del historial y devuelve *por qué* una operación se marcaría para revisión
        (factores SHAP). Requiere el artefacto entrenado (`manage.py train_risk_model`) y
        las dependencias `catboost`/`shap`; si faltan, responde 503.
        """
        tx = self.get_object()
        try:
            from .ml_risk import RiskReviewModel, features_from_transaction
        except ImportError as exc:  # catboost/shap no instalados
            return Response(
                {'detail': f'Explicabilidad ML no disponible: {exc}'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        try:
            feats = features_from_transaction(tx)
            explanation = RiskReviewModel().explain(feats)
        except FileNotFoundError as exc:
            return Response(
                {'detail': str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as exc:  # fail-safe: nunca romper el flujo por el modelo
            return Response(
                {'detail': f'No se pudo generar la explicación: {exc}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response({
            'transaction': tx.transaction_number,
            'probability': explanation.probability,
            'decision': explanation.decision,
            'base_value': explanation.base_value,
            'rule_engine': {
                'fraud_score': float(tx.fraud_score) if tx.fraud_score is not None else None,
                'approval_required': tx.approval_required,
                'fraud_flags': tx.fraud_flags,
            },
            'top_factors': explanation.top_factors,
            'features': feats,
        })


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated, IsCompanyMember]

    def get_queryset(self):
        from django.db.models import Count, Sum
        user = self.request.user

        queryset = Customer.objects.annotate(
            tx_count=Count('transactions', distinct=True),
            tx_volume=Sum('transactions__amount_from'),
        )

        # Tenant isolation
        if getattr(user, 'company_id', None):
            queryset = queryset.filter(company_id=user.company_id)

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(document_number__icontains=search) |
                Q(full_name__icontains=search) |
                Q(phone__icontains=search)
            )

        frequent_only = self.request.query_params.get('frequent_only')
        if frequent_only == 'true':
            queryset = queryset.filter(is_frequent=True)

        return queryset.order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(company=self.request.user.company)

    @action(detail=False, methods=['GET'], url_path='search')
    @rate_limit(requests=30, window=60, scope='user')
    def search(self, request):
        document = request.query_params.get('document')
        if not document:
            return Response(
                {'error': 'Número de documento requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            # Aislamiento multi-tenant: document_number es único POR empresa;
            # sin este filtro se filtraban clientes de otras empresas (y el
            # .get() podía romper con MultipleObjectsReturned).
            customer = Customer.objects.get(
                document_number=document,
                company=request.user.company,
            )
            return Response(CustomerSerializer(customer).data)
        except Customer.DoesNotExist:
            return Response(
                {'message': 'Cliente no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['GET'], url_path='transactions')
    def transactions(self, request, pk=None):
        customer = self.get_object()
        from transactions.models import Transaction
        txs = Transaction.objects.filter(
            customer=customer
        ).order_by('-created_at')[:50]
        from transactions.serializers import TransactionSerializer
        return Response(TransactionSerializer(txs, many=True).data)

    @action(detail=True, methods=['POST'], url_path='mark-frequent')
    def mark_frequent(self, request, pk=None):
        customer = self.get_object()
        customer.is_frequent = True
        customer.save()
        return Response({'success': True})