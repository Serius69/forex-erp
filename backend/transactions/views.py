# transactions/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from datetime import datetime, timedelta
from django.utils.dateparse import parse_date
from django.http import HttpResponse
from .models import Transaction, Customer, TransactionDocument
from .serializers import (
    TransactionSerializer, CustomerSerializer,
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
        if date_from:
            d = parse_date(str(date_from))
            if d:
                queryset = queryset.filter(created_at__date__gte=d)
        if date_to:
            d = parse_date(str(date_to))
            if d:
                queryset = queryset.filter(created_at__date__lte=d)
        if tx_status:
            queryset = queryset.filter(status=tx_status)
        if transaction_type:
            queryset = queryset.filter(transaction_type=transaction_type)
        
        return queryset.select_related(
            'customer', 'currency_from', 'currency_to',
            'cashier', 'branch', 'supervisor',
        ).prefetch_related('documents').order_by('-created_at')
    
    def list(self, request, *args, **kwargs):
        """Override to return structured JSON on DB/serialization errors."""
        try:
            return super().list(request, *args, **kwargs)
        except Exception as exc:
            import logging as _log
            _log.getLogger('transactions').exception('TX_LIST_FAILED err=%s', exc)
            return Response(
                {'error': 'Error al obtener transacciones', 'detail': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def get_serializer_class(self):
        if self.action == 'create':
            return TransactionCreateSerializer
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
            if cur_from.code == 'USD':
                return amount_from > 5000
            if cur_from.code == 'BOB':
                return amount_from > 35000
            return amount_from * exchange_rate > 35000

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

            # Validar PIN contra todos los supervisores/admins
            from users.models import User as UserModel
            for sup in UserModel.objects.filter(role__in=('ADMIN', 'SUPERVISOR')):
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

                # Cuantizar montos con precisión financiera
                from core.finance import quantize_amount, quantize_money, quantize_rate
                tx = Transaction.objects.create(
                    transaction_number    = tx_num,
                    transaction_type      = vd['transaction_type'],
                    transaction_category  = vd.get('transaction_category', 'REPORTABLE'),
                    status                = 'COMPLETED',
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
                    completed_at          = now,
                )

                # Actualizar inventario de divisas.
                # NO envuelto en try/except: si falla, el atomic block hace rollback
                # completo y los efectos de capital también se deshacen.
                service = TransactionService()
                service._update_inventory(tx)

                # ── Efectos BOB: CapitalComposicion + CashFlowLog ─────────────
                # BUY  → BOB disminuye (empresa paga bolivianos)
                # SELL → BOB aumenta  (empresa recibe bolivianos)
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
            reversal = transaction.reverse(request.user, reason)
            
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
        
        transactions = self.get_queryset().filter(created_at__date=target_date)
        
        summary = {
            'date': target_date,
            'total_transactions': transactions.count(),
            'by_type': {
                'buy': transactions.filter(transaction_type='BUY').count(),
                'sell': transactions.filter(transaction_type='SELL').count(),
            },
            'by_currency': {},
            'total_volume_bob': 0,
            'by_payment_method': {},
            'by_hour': []
        }
        
        # Resumen por divisa
        currencies = transactions.values('currency_from__code').distinct()
        for currency in currencies:
            code = currency['currency_from__code']
            currency_transactions = transactions.filter(currency_from__code=code)
            
            summary['by_currency'][code] = {
                'buy': {
                    'count': currency_transactions.filter(transaction_type='BUY').count(),
                    'volume': currency_transactions.filter(
                        transaction_type='BUY'
                    ).aggregate(Sum('amount_from'))['amount_from__sum'] or 0
                },
                'sell': {
                    'count': currency_transactions.filter(transaction_type='SELL').count(),
                    'volume': currency_transactions.filter(
                        transaction_type='SELL'
                    ).aggregate(Sum('amount_from'))['amount_from__sum'] or 0
                }
            }
        
        # Volumen total en BOB
        summary['total_volume_bob'] = transactions.aggregate(
            Sum('amount_to')
        )['amount_to__sum'] or 0
        
        # Por método de pago
        payment_methods = transactions.values('payment_method').annotate(
            count=Count('id'),
            volume=Sum('amount_to')
        )
        
        for pm in payment_methods:
            summary['by_payment_method'][pm['payment_method']] = {
                'count': pm['count'],
                'volume': float(pm['volume'] or 0)
            }
        
        # Por hora del día
        for hour in range(24):
            hour_transactions = transactions.filter(
                created_at__hour=hour
            )
            summary['by_hour'].append({
                'hour': hour,
                'count': hour_transactions.count(),
                'volume': float(
                    hour_transactions.aggregate(
                        Sum('amount_to')
                    )['amount_to__sum'] or 0
                )
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
        from .audit import create_audit_log, snapshot_transaction

        prev = snapshot_transaction(tx)
        tx.approval_required = False
        tx.approved_by = request.user
        tx.approved_at = tz.now()
        tx.status = 'APPROVED'
        tx.save(update_fields=['approval_required', 'approved_by', 'approved_at', 'status', 'updated_at'])

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