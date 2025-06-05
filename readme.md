# Sistema Integral ERP/CRM para Casa de Cambio de Divisas

## Arquitectura del Sistema

### Stack Tecnológico
- **Backend**: Python (Django REST Framework)
- **Base de datos**: PostgreSQL
- **Machine Learning**: Prophet, scikit-learn, TensorFlow
- **Frontend**: React + Material-UI
- **App Móvil**: React Native
- **Cache**: Redis
- **Tareas asíncronas**: Celery
- **Websockets**: Django Channels
- **Hosting**: AWS/DigitalOcean

## Estructura del Proyecto

```
forex-erp/
├── backend/
│   ├── core/
│   ├── predictions/
│   ├── transactions/
│   ├── inventory/
│   ├── reports/
│   ├── users/
│   ├── rates/
│   └── api/
├── frontend/
│   ├── src/
│   └── public/
├── mobile/
└── ml-models/
```

## 1. Módulo de Predicción de Precios

### Modelo de Datos

```python
# backend/predictions/models.py
from django.db import models
from django.contrib.postgres.fields import JSONField

class CurrencyPrediction(models.Model):
    currency_pair = models.CharField(max_length=10)  # USD/BOB, EUR/BOB
    prediction_date = models.DateTimeField()
    predicted_buy_rate = models.DecimalField(max_digits=10, decimal_places=4)
    predicted_sell_rate = models.DecimalField(max_digits=10, decimal_places=4)
    confidence_score = models.FloatField()
    model_used = models.CharField(max_length=50)
    external_factors = JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['currency_pair', 'prediction_date']),
        ]

class HistoricalRate(models.Model):
    currency_pair = models.CharField(max_length=10)
    date = models.DateTimeField()
    official_rate = models.DecimalField(max_digits=10, decimal_places=4)
    commercial_buy_rate = models.DecimalField(max_digits=10, decimal_places=4)
    commercial_sell_rate = models.DecimalField(max_digits=10, decimal_places=4)
    volume = models.DecimalField(max_digits=15, decimal_places=2)
    source = models.CharField(max_length=50)
```

### Servicio de Predicción ML

```python
# backend/predictions/ml_service.py
import pandas as pd
import numpy as np
from prophet import Prophet
from sklearn.ensemble import RandomForestRegressor
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense
import joblib
from datetime import datetime, timedelta

class ForexPredictor:
    def __init__(self):
        self.models = {
            'prophet': None,
            'lstm': None,
            'rf': None
        }
        
    def train_prophet_model(self, data):
        """Entrena modelo Prophet para predicción de series temporales"""
        df = pd.DataFrame(data)
        df['ds'] = pd.to_datetime(df['date'])
        df['y'] = df['rate']
        
        model = Prophet(
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=True,
            changepoint_prior_scale=0.05
        )
        
        # Agregar regresores externos
        model.add_regressor('international_rate')
        model.add_regressor('interest_rate')
        
        model.fit(df)
        self.models['prophet'] = model
        
        return model
    
    def train_lstm_model(self, data, sequence_length=60):
        """Entrena modelo LSTM para predicción"""
        # Preparar datos
        scaled_data = self._scale_data(data)
        X, y = self._create_sequences(scaled_data, sequence_length)
        
        # Construir modelo
        model = Sequential([
            LSTM(50, return_sequences=True, input_shape=(sequence_length, 1)),
            LSTM(50, return_sequences=False),
            Dense(25),
            Dense(1)
        ])
        
        model.compile(optimizer='adam', loss='mean_squared_error')
        model.fit(X, y, batch_size=32, epochs=50, validation_split=0.1)
        
        self.models['lstm'] = model
        return model
    
    def predict_rates(self, currency_pair, horizon=24):
        """Genera predicciones para las próximas 'horizon' horas"""
        predictions = {}
        
        # Prophet prediction
        if self.models['prophet']:
            future = self.models['prophet'].make_future_dataframe(
                periods=horizon, 
                freq='H'
            )
            forecast = self.models['prophet'].predict(future)
            predictions['prophet'] = forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']]
        
        # LSTM prediction
        if self.models['lstm']:
            lstm_pred = self._predict_lstm(horizon)
            predictions['lstm'] = lstm_pred
        
        # Ensemble prediction
        ensemble_pred = self._ensemble_predictions(predictions)
        
        return {
            'currency_pair': currency_pair,
            'predictions': ensemble_pred,
            'confidence': self._calculate_confidence(predictions),
            'timestamp': datetime.now()
        }
    
    def _ensemble_predictions(self, predictions):
        """Combina predicciones de múltiples modelos"""
        # Implementar lógica de ensemble
        pass
```

### API de Predicciones

```python
# backend/predictions/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import CurrencyPrediction, HistoricalRate
from .ml_service import ForexPredictor
from .tasks import update_predictions_task

class PredictionViewSet(viewsets.ModelViewSet):
    queryset = CurrencyPrediction.objects.all()
    serializer_class = CurrencyPredictionSerializer
    
    @action(detail=False, methods=['GET'])
    def current_predictions(self, request):
        """Obtiene predicciones actuales para todas las divisas"""
        currency_pair = request.query_params.get('pair', 'USD/BOB')
        
        predictions = CurrencyPrediction.objects.filter(
            currency_pair=currency_pair,
            prediction_date__gte=timezone.now()
        ).order_by('prediction_date')[:24]
        
        serializer = self.get_serializer(predictions, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['POST'])
    def train_models(self, request):
        """Entrena modelos con datos históricos"""
        update_predictions_task.delay()
        return Response({'status': 'Training started'})
```

## 2. Módulo de Registro de Transacciones

### Modelos de Transacciones

```python
# backend/transactions/models.py
from django.db import models
from django.contrib.auth import get_user_model
from decimal import Decimal

User = get_user_model()

class Customer(models.Model):
    document_type = models.CharField(max_length=20, choices=[
        ('CI', 'Cédula de Identidad'),
        ('NIT', 'NIT'),
        ('PASSPORT', 'Pasaporte'),
    ])
    document_number = models.CharField(max_length=50, unique=True)
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    is_frequent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.full_name} - {self.document_number}"

class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('BUY', 'Compra'),
        ('SELL', 'Venta'),
    ]
    
    PAYMENT_METHODS = [
        ('CASH', 'Efectivo'),
        ('TRANSFER', 'Transferencia'),
        ('QR', 'QR'),
    ]
    
    transaction_number = models.CharField(max_length=20, unique=True)
    transaction_type = models.CharField(max_length=4, choices=TRANSACTION_TYPES)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    currency_from = models.CharField(max_length=3)
    currency_to = models.CharField(max_length=3)
    amount_from = models.DecimalField(max_digits=15, decimal_places=2)
    amount_to = models.DecimalField(max_digits=15, decimal_places=2)
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4)
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHODS)
    cashier = models.ForeignKey(User, on_delete=models.PROTECT)
    branch = models.ForeignKey('Branch', on_delete=models.PROTECT)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    @property
    def profit_margin(self):
        """Calcula el margen de ganancia de la transacción"""
        # Implementar lógica de cálculo
        pass
    
    def generate_receipt(self):
        """Genera comprobante en PDF"""
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        # Implementar generación de PDF
        pass
```

### API de Transacciones

```python
# backend/transactions/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from .models import Transaction, Customer
from .serializers import TransactionSerializer
from inventory.models import CurrencyInventory

class TransactionViewSet(viewsets.ModelViewSet):
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    
    def create(self, request):
        """Crea una nueva transacción y actualiza inventario"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        with transaction.atomic():
            # Crear transacción
            trans = serializer.save(cashier=request.user)
            
            # Actualizar inventario
            inventory = CurrencyInventory.objects.get(
                currency=trans.currency_from,
                branch=trans.branch
            )
            
            if trans.transaction_type == 'BUY':
                inventory.add_currency(trans.amount_from, trans.exchange_rate)
            else:
                inventory.remove_currency(trans.amount_from)
            
            # Generar comprobante
            receipt_url = trans.generate_receipt()
            
        return Response({
            'transaction': serializer.data,
            'receipt_url': receipt_url
        }, status=status.HTTP_201_CREATED)
    
    @action(detail=False, methods=['GET'])
    def daily_summary(self, request):
        """Resumen diario de transacciones"""
        date = request.query_params.get('date', timezone.now().date())
        
        summary = Transaction.objects.filter(
            created_at__date=date
        ).aggregate(
            total_buy=Sum('amount_to', filter=Q(transaction_type='BUY')),
            total_sell=Sum('amount_from', filter=Q(transaction_type='SELL')),
            transaction_count=Count('id')
        )
        
        return Response(summary)
```

## 3. Módulo de Control de Stock

### Modelos de Inventario

```python
# backend/inventory/models.py
from django.db import models
from django.db.models import Avg
from decimal import Decimal

class CurrencyInventory(models.Model):
    currency = models.CharField(max_length=3)
    branch = models.ForeignKey('Branch', on_delete=models.CASCADE)
    physical_balance = models.DecimalField(max_digits=15, decimal_places=2)
    digital_balance = models.DecimalField(max_digits=15, decimal_places=2)
    minimum_stock = models.DecimalField(max_digits=15, decimal_places=2)
    maximum_stock = models.DecimalField(max_digits=15, decimal_places=2)
    weighted_average_cost = models.DecimalField(max_digits=10, decimal_places=4)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['currency', 'branch']
    
    @property
    def total_balance(self):
        return self.physical_balance + self.digital_balance
    
    @property
    def needs_replenishment(self):
        return self.total_balance < self.minimum_stock
    
    def add_currency(self, amount, rate):
        """Añade divisas al inventario y actualiza el costo promedio"""
        total_cost = (self.total_balance * self.weighted_average_cost) + (amount * rate)
        new_balance = self.total_balance + amount
        
        self.weighted_average_cost = total_cost / new_balance if new_balance > 0 else 0
        self.physical_balance += amount
        self.save()
        
        # Registrar movimiento
        InventoryMovement.objects.create(
            inventory=self,
            movement_type='IN',
            amount=amount,
            rate=rate,
            balance_after=self.total_balance
        )
    
    def remove_currency(self, amount):
        """Retira divisas del inventario"""
        if amount > self.total_balance:
            raise ValueError("Saldo insuficiente")
        
        self.physical_balance -= amount
        self.save()
        
        # Registrar movimiento
        InventoryMovement.objects.create(
            inventory=self,
            movement_type='OUT',
            amount=amount,
            rate=self.weighted_average_cost,
            balance_after=self.total_balance
        )

class InventoryMovement(models.Model):
    MOVEMENT_TYPES = [
        ('IN', 'Entrada'),
        ('OUT', 'Salida'),
        ('TRANSFER', 'Transferencia'),
        ('ADJUSTMENT', 'Ajuste'),
    ]
    
    inventory = models.ForeignKey(CurrencyInventory, on_delete=models.CASCADE)
    movement_type = models.CharField(max_length=10, choices=MOVEMENT_TYPES)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    rate = models.DecimalField(max_digits=10, decimal_places=4)
    balance_after = models.DecimalField(max_digits=15, decimal_places=2)
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

### Sistema de Alertas

```python
# backend/inventory/alerts.py
from django.core.mail import send_mail
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import CurrencyInventory
from notifications.models import Alert

class InventoryAlertSystem:
    @staticmethod
    def check_inventory_levels():
        """Verifica niveles de inventario y genera alertas"""
        low_stock = CurrencyInventory.objects.filter(
            total_balance__lt=F('minimum_stock')
        )
        
        for inventory in low_stock:
            Alert.objects.create(
                type='LOW_STOCK',
                severity='HIGH',
                title=f'Stock bajo de {inventory.currency}',
                message=f'El stock de {inventory.currency} en {inventory.branch} está por debajo del mínimo. Balance actual: {inventory.total_balance}',
                currency=inventory.currency,
                branch=inventory.branch
            )
            
            # Enviar notificación por email
            send_mail(
                subject=f'Alerta: Stock bajo de {inventory.currency}',
                message=f'Requiere reposición urgente. Balance: {inventory.total_balance}',
                from_email='sistema@casadecambio.com',
                recipient_list=['gerencia@casadecambio.com']
            )
```

## 4. Módulo de Reportes Financieros

### Generación de Reportes

```python
# backend/reports/services.py
from django.db.models import Sum, Count, Avg, F, Q
from datetime import datetime, timedelta
import pandas as pd
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

class ReportGenerator:
    def __init__(self, start_date, end_date, branch=None):
        self.start_date = start_date
        self.end_date = end_date
        self.branch = branch
    
    def generate_daily_report(self):
        """Genera reporte diario de operaciones"""
        transactions = Transaction.objects.filter(
            created_at__date=self.start_date
        )
        
        if self.branch:
            transactions = transactions.filter(branch=self.branch)
        
        # Resumen por tipo de divisa
        currency_summary = transactions.values('currency_from').annotate(
            total_buy=Sum('amount_from', filter=Q(transaction_type='BUY')),
            total_sell=Sum('amount_from', filter=Q(transaction_type='SELL')),
            avg_rate=Avg('exchange_rate'),
            transaction_count=Count('id')
        )
        
        # Utilidades
        profits = self._calculate_profits(transactions)
        
        # Generar Excel
        wb = Workbook()
        ws = wb.active
        ws.title = "Reporte Diario"
        
        # Headers
        headers = ['Divisa', 'Compras', 'Ventas', 'Tasa Promedio', 'Transacciones', 'Utilidad']
        ws.append(headers)
        
        # Data
        for currency in currency_summary:
            ws.append([
                currency['currency_from'],
                currency['total_buy'] or 0,
                currency['total_sell'] or 0,
                currency['avg_rate'],
                currency['transaction_count'],
                profits.get(currency['currency_from'], 0)
            ])
        
        # Guardar archivo
        filename = f"reporte_diario_{self.start_date}.xlsx"
        wb.save(filename)
        
        return filename
    
    def generate_regulatory_report(self):
        """Genera reporte para autoridades regulatorias"""
        # Transacciones superiores al límite
        high_value_transactions = Transaction.objects.filter(
            created_at__range=[self.start_date, self.end_date],
            amount_from__gte=10000  # Límite en USD
        ).select_related('customer')
        
        # Clientes frecuentes
        frequent_customers = Customer.objects.annotate(
            transaction_count=Count('transaction')
        ).filter(
            transaction_count__gte=5,
            transaction__created_at__range=[self.start_date, self.end_date]
        )
        
        # Generar PDF
        pdf_filename = f"reporte_regulatorio_{self.start_date}_{self.end_date}.pdf"
        doc = SimpleDocTemplate(pdf_filename, pagesize=A4)
        
        # Implementar generación de PDF con reportlab
        
        return pdf_filename
    
    def _calculate_profits(self, transactions):
        """Calcula utilidades por divisa"""
        profits = {}
        
        for currency in ['USD', 'EUR', 'BRL', 'ARS']:
            buy_transactions = transactions.filter(
                transaction_type='BUY',
                currency_from=currency
            )
            sell_transactions = transactions.filter(
                transaction_type='SELL',
                currency_from=currency
            )
            
            # Calcular margen basado en costo promedio ponderado
            # Implementar lógica de cálculo
            
        return profits
```

## 5. Módulo de Administración de Usuarios

### Modelos de Usuario y Permisos

```python
# backend/users/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    ROLE_CHOICES = [
        ('ADMIN', 'Administrador'),
        ('SUPERVISOR', 'Supervisor'),
        ('CASHIER', 'Cajero'),
    ]
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True)
    pin = models.CharField(max_length=6, blank=True)
    phone = models.CharField(max_length=20)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        permissions = [
            ('can_modify_rates', 'Puede modificar tasas de cambio'),
            ('can_view_reports', 'Puede ver reportes'),
            ('can_manage_inventory', 'Puede gestionar inventario'),
            ('can_approve_high_value', 'Puede aprobar transacciones de alto valor'),
        ]

class UserActivity(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    action = models.CharField(max_length=100)
    details = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField()
    user_agent = models.CharField(max_length=200)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
```

### Sistema de Autenticación

```python
# backend/users/authentication.py
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
import pyotp

class TwoFactorAuthentication:
    @staticmethod
    def generate_secret():
        """Genera secret para 2FA"""
        return pyotp.random_base32()
    
    @staticmethod
    def verify_token(user, token):
        """Verifica token 2FA"""
        totp = pyotp.TOTP(user.two_factor_secret)
        return totp.verify(token, valid_window=1)

class CustomAuthentication(JWTAuthentication):
    def authenticate(self, request):
        # Verificar JWT
        validated_token = self.get_validated_token(
            self.get_raw_token(self.get_header(request))
        )
        
        # Verificar PIN para operaciones sensibles
        if request.path.startswith('/api/transactions/'):
            pin = request.headers.get('X-User-PIN')
            if not pin or not request.user.check_pin(pin):
                raise exceptions.AuthenticationFailed('PIN inválido')
        
        return self.get_user(validated_token), validated_token
```

## 6. Módulo de Gestión de Tasas

### Servicio de Tasas de Cambio

```python
# backend/rates/services.py
import requests
from bs4 import BeautifulSoup
from decimal import Decimal
from django.core.cache import cache
from .models import ExchangeRate, RateConfiguration

class RateManagementService:
    def __init__(self):
        self.sources = {
            'BCB': 'https://www.bcb.gob.bo/',
            'BCP': 'https://www.bcp.com.bo/',
        }
    
    def fetch_official_rates(self):
        """Obtiene tasas oficiales del BCB"""
        try:
            response = requests.get(self.sources['BCB'])
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Parsear tasas del HTML
            rates = {}
            # Implementar scraping específico
            
            # Guardar en base de datos
            for currency, rate in rates.items():
                ExchangeRate.objects.create(
                    currency_pair=f"{currency}/BOB",
                    official_rate=rate,
                    source='BCB'
                )
            
            return rates
        except Exception as e:
            logger.error(f"Error fetching rates: {e}")
            return None
    
    def calculate_commercial_rates(self, currency_pair):
        """Calcula tasas comerciales con márgenes configurados"""
        config = RateConfiguration.objects.get(
            currency_pair=currency_pair,
            is_active=True
        )
        
        # Obtener tasa oficial
        official_rate = cache.get(f'official_rate_{currency_pair}')
        if not official_rate:
            latest_rate = ExchangeRate.objects.filter(
                currency_pair=currency_pair
            ).latest('created_at')
            official_rate = latest_rate.official_rate
            cache.set(f'official_rate_{currency_pair}', official_rate, 300)
        
        # Aplicar márgenes dinámicos
        hour = timezone.now().hour
        
        if 8 <= hour <= 12:  # Horario de alta demanda
            buy_margin = config.buy_margin_morning
            sell_margin = config.sell_margin_morning
        elif 14 <= hour <= 18:  # Horario normal
            buy_margin = config.buy_margin_afternoon
            sell_margin = config.sell_margin_afternoon
        else:  # Horario de baja demanda
            buy_margin = config.buy_margin_evening
            sell_margin = config.sell_margin_evening
        
        # Calcular tasas comerciales
        buy_rate = official_rate * (1 - buy_margin / 100)
        sell_rate = official_rate * (1 + sell_margin / 100)
        
        return {
            'buy': buy_rate,
            'sell': sell_rate,
            'official': official_rate,
            'spread': sell_rate - buy_rate
        }
```

## 7. Frontend React

### Dashboard Principal

```jsx
// frontend/src/components/Dashboard.jsx
import React, { useState, useEffect } from 'react';
import { Grid, Paper, Typography, Card, CardContent } from '@mui/material';
import { Line, Bar } from 'react-chartjs-2';
import { useWebSocket } from '../hooks/useWebSocket';
import RateDisplay from './RateDisplay';
import TransactionForm from './TransactionForm';
import AlertsPanel from './AlertsPanel';

const Dashboard = () => {
  const [rates, setRates] = useState({});
  const [predictions, setPredictions] = useState([]);
  const [summary, setSummary] = useState({});
  const { lastMessage } = useWebSocket('ws://localhost:8000/ws/rates/');

  useEffect(() => {
    // Actualizar tasas en tiempo real
    if (lastMessage) {
      setRates(JSON.parse(lastMessage.data));
    }
  }, [lastMessage]);

  useEffect(() => {
    // Cargar datos iniciales
    fetchDashboardData();
  }, []);

  const fetchDashboardData = async () => {
    try {
      const [ratesRes, predictionsRes, summaryRes] = await Promise.all([
        fetch('/api/rates/current/'),
        fetch('/api/predictions/current/'),
        fetch('/api/transactions/daily-summary/')
      ]);

      setRates(await ratesRes.json());
      setPredictions(await predictionsRes.json());
      setSummary(await summaryRes.json());
    } catch (error) {
      console.error('Error loading dashboard data:', error);
    }
  };

  const predictionChartData = {
    labels: predictions.map(p => new Date(p.prediction_date).toLocaleTimeString()),
    datasets: [
      {
        label: 'Predicción Compra',
        data: predictions.map(p => p.predicted_buy_rate),
        borderColor: 'rgb(75, 192, 192)',
        backgroundColor: 'rgba(75, 192, 192, 0.2)',
      },
      {
        label: 'Predicción Venta',
        data: predictions.map(p => p.predicted_sell_rate),
        borderColor: 'rgb(255, 99, 132)',
        backgroundColor: 'rgba(255, 99, 132, 0.2)',
      }
    ]
  };

  return (
    <Grid container spacing={3}>
      {/* Tasas Actuales */}
      <Grid item xs={12} md={8}>
        <Paper elevation={3} sx={{ p: 2 }}>
          <Typography variant="h6" gutterBottom>
            Tasas de Cambio Actuales
          </Typography>
          <Grid container spacing={2}>
            {Object.entries(rates).map(([currency, rate]) => (
              <Grid item xs={6} md={3} key={currency}>
                <RateDisplay 
                  currency={currency}
                  buyRate={rate.buy}
                  sellRate={rate.sell}
                />
              </Grid>
            ))}
          </Grid>
        </Paper>
      </Grid>

      {/* Alertas */}
      <Grid item xs={12} md={4}>
        <AlertsPanel />
      </Grid>

      {/* Predicciones */}
      <Grid item xs={12} md={8}>
        <Paper elevation={3} sx={{ p: 2 }}>
          <Typography variant="h6" gutterBottom>
            Predicciones de Tasas (24h)
          </Typography>
          <Line data={predictionChartData} />
        </Paper>
      </Grid>

      {/* Resumen Diario */}
      <Grid item xs={12} md={4}>
        <Card>
          <CardContent>
            <Typography variant="h6">Resumen del Día</Typography>
            <Typography>Transacciones: {summary.transaction_count || 0}</Typography>
            <Typography>Compras: ${summary.total_buy || 0}</Typography>
            <Typography>Ventas: ${summary.total_sell || 0}</Typography>
            <Typography color="primary">
              Utilidad: ${summary.total_profit || 0}
            </Typography>
          </CardContent>
        </Card>
      </Grid>

### Formulario de Transacciones

```jsx
// frontend/src/components/TransactionForm.jsx
import React, { useState } from 'react';
import {
  Paper,
  TextField,
  Button,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Grid,
  Typography,
  Autocomplete,
  RadioGroup,
  Radio,
  FormControlLabel,
  Alert
} from '@mui/material';
import { useForm, Controller } from 'react-hook-form';
import { useMutation } from 'react-query';
import axios from 'axios';

const TransactionForm = ({ onSuccess }) => {
  const [transactionType, setTransactionType] = useState('SELL');
  const [customer, setCustomer] = useState(null);
  const { control, handleSubmit, watch, setValue, reset } = useForm();
  const [showReceipt, setShowReceipt] = useState(false);

  const createTransaction = useMutation(
    (data) => axios.post('/api/transactions/', data),
    {
      onSuccess: (response) => {
        reset();
        setShowReceipt(true);
        onSuccess();
        // Abrir comprobante
        window.open(response.data.receipt_url, '_blank');
      }
    }
  );

  const searchCustomer = async (documentNumber) => {
    if (documentNumber.length < 5) return;
    
    try {
      const response = await axios.get(`/api/customers/search/?document=${documentNumber}`);
      if (response.data) {
        setCustomer(response.data);
        setValue('customer_name', response.data.full_name);
      }
    } catch (error) {
      console.log('Cliente no encontrado');
    }
  };

  const calculateExchange = (amount, rate) => {
    if (!amount || !rate) return 0;
    return transactionType === 'BUY' 
      ? (amount * rate).toFixed(2)
      : (amount / rate).toFixed(2);
  };

  const onSubmit = (data) => {
    const transaction = {
      ...data,
      transaction_type: transactionType,
      customer_id: customer?.id,
      amount_to: calculateExchange(data.amount_from, data.exchange_rate)
    };
    
    createTransaction.mutate(transaction);
  };

  return (
    <Paper elevation={3} sx={{ p: 3 }}>
      <Typography variant="h6" gutterBottom>
        Nueva Transacción
      </Typography>

      <form onSubmit={handleSubmit(onSubmit)}>
        <Grid container spacing={3}>
          {/* Tipo de Transacción */}
          <Grid item xs={12}>
            <RadioGroup
              row
              value={transactionType}
              onChange={(e) => setTransactionType(e.target.value)}
            >
              <FormControlLabel value="SELL" control={<Radio />} label="Venta de Divisas" />
              <FormControlLabel value="BUY" control={<Radio />} label="Compra de Divisas" />
            </RadioGroup>
          </Grid>

          {/* Datos del Cliente */}
          <Grid item xs={12} md={4}>
            <Controller
              name="document_number"
              control={control}
              defaultValue=""
              rules={{ required: 'Documento requerido' }}
              render={({ field }) => (
                <TextField
                  {...field}
                  label="Número de Documento"
                  fullWidth
                  onChange={(e) => {
                    field.onChange(e);
                    searchCustomer(e.target.value);
                  }}
                />
              )}
            />
          </Grid>

          <Grid item xs={12} md={8}>
            <Controller
              name="customer_name"
              control={control}
              defaultValue=""
              rules={{ required: 'Nombre requerido' }}
              render={({ field }) => (
                <TextField
                  {...field}
                  label="Nombre del Cliente"
                  fullWidth
                  disabled={!!customer}
                />
              )}
            />
          </Grid>

          {/* Divisas */}
          <Grid item xs={12} md={3}>
            <Controller
              name="currency_from"
              control={control}
              defaultValue="USD"
              render={({ field }) => (
                <FormControl fullWidth>
                  <InputLabel>Divisa</InputLabel>
                  <Select {...field} label="Divisa">
                    <MenuItem value="USD">USD - Dólar</MenuItem>
                    <MenuItem value="EUR">EUR - Euro</MenuItem>
                    <MenuItem value="BRL">BRL - Real</MenuItem>
                    <MenuItem value="ARS">ARS - Peso Argentino</MenuItem>
                  </Select>
                </FormControl>
              )}
            />
          </Grid>

          <Grid item xs={12} md={3}>
            <Controller
              name="amount_from"
              control={control}
              defaultValue=""
              rules={{ required: 'Monto requerido', min: 0.01 }}
              render={({ field }) => (
                <TextField
                  {...field}
                  label={transactionType === 'BUY' ? 'Monto a Comprar' : 'Monto a Vender'}
                  type="number"
                  fullWidth
                  InputProps={{ inputProps: { step: 0.01 } }}
                />
              )}
            />
          </Grid>

          <Grid item xs={12} md={3}>
            <Controller
              name="exchange_rate"
              control={control}
              defaultValue=""
              rules={{ required: 'Tasa requerida' }}
              render={({ field }) => (
                <TextField
                  {...field}
                  label="Tasa de Cambio"
                  type="number"
                  fullWidth
                  InputProps={{ inputProps: { step: 0.0001 } }}
                />
              )}
            />
          </Grid>

          <Grid item xs={12} md={3}>
            <TextField
              label="Total en Bolivianos"
              value={calculateExchange(
                watch('amount_from'),
                watch('exchange_rate')
              )}
              fullWidth
              disabled
              InputProps={{
                startAdornment: 'Bs. '
              }}
            />
          </Grid>

          {/* Método de Pago */}
          <Grid item xs={12} md={6}>
            <Controller
              name="payment_method"
              control={control}
              defaultValue="CASH"
              render={({ field }) => (
                <FormControl fullWidth>
                  <InputLabel>Método de Pago</InputLabel>
                  <Select {...field} label="Método de Pago">
                    <MenuItem value="CASH">Efectivo</MenuItem>
                    <MenuItem value="TRANSFER">Transferencia</MenuItem>
                    <MenuItem value="QR">QR</MenuItem>
                  </Select>
                </FormControl>
              )}
            />
          </Grid>

          <Grid item xs={12} md={6}>
            <Controller
              name="notes"
              control={control}
              defaultValue=""
              render={({ field }) => (
                <TextField
                  {...field}
                  label="Notas (Opcional)"
                  fullWidth
                  multiline
                  rows={2}
                />
              )}
            />
          </Grid>

          {/* Botones */}
          <Grid item xs={12}>
            <Button
              type="submit"
              variant="contained"
              color="primary"
              size="large"
              disabled={createTransaction.isLoading}
              sx={{ mr: 2 }}
            >
              Registrar Transacción
            </Button>
            <Button
              variant="outlined"
              onClick={() => reset()}
            >
              Limpiar
            </Button>
          </Grid>
        </Grid>
      </form>

      {createTransaction.isSuccess && (
        <Alert severity="success" sx={{ mt: 2 }}>
          Transacción registrada exitosamente
        </Alert>
      )}
    </Paper>
  );
};

export default TransactionForm;
```

## 8. App Móvil React Native

### Pantalla Principal Móvil

```jsx
// mobile/src/screens/HomeScreen.js
import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  TouchableOpacity
} from 'react-native';
import { Card, Button, Badge } from 'react-native-elements';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { LineChart } from 'react-native-chart-kit';
import api from '../services/api';

const HomeScreen = ({ navigation }) => {
  const [rates, setRates] = useState({});
  const [predictions, setPredictions] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    loadData();
    // Actualizar cada minuto
    const interval = setInterval(loadData, 60000);
    return () => clearInterval(interval);
  }, []);

  const loadData = async () => {
    try {
      const [ratesData, predictionsData, alertsData] = await Promise.all([
        api.get('/rates/current/'),
        api.get('/predictions/current/'),
        api.get('/alerts/active/')
      ]);

      setRates(ratesData.data);
      setPredictions(predictionsData.data);
      setAlerts(alertsData.data);
    } catch (error) {
      console.error('Error loading data:', error);
    }
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await loadData();
    setRefreshing(false);
  };

  const chartData = {
    labels: predictions.slice(0, 6).map(p => 
      new Date(p.prediction_date).getHours() + 'h'
    ),
    datasets: [
      {
        data: predictions.slice(0, 6).map(p => p.predicted_sell_rate),
        color: (opacity = 1) => `rgba(134, 65, 244, ${opacity})`,
        strokeWidth: 2
      }
    ]
  };

  return (
    <ScrollView
      style={styles.container}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
      }
    >
      {/* Alertas */}
      {alerts.length > 0 && (
        <Card containerStyle={styles.alertCard}>
          <View style={styles.alertHeader}>
            <Text style={styles.alertTitle}>Alertas</Text>
            <Badge value={alerts.length} status="error" />
          </View>
          {alerts.map((alert, index) => (
            <Text key={index} style={styles.alertText}>
              • {alert.message}
            </Text>
          ))}
        </Card>
      )}

      {/* Tasas Actuales */}
      <Card>
        <Text style={styles.sectionTitle}>Tasas de Cambio</Text>
        <View style={styles.ratesGrid}>
          {Object.entries(rates).map(([currency, rate]) => (
            <View key={currency} style={styles.rateItem}>
              <Text style={styles.currency}>{currency}</Text>
              <Text style={styles.rateLabel}>Compra</Text>
              <Text style={styles.rateValue}>{rate.buy}</Text>
              <Text style={styles.rateLabel}>Venta</Text>
              <Text style={styles.rateValue}>{rate.sell}</Text>
            </View>
          ))}
        </View>
      </Card>

      {/* Predicciones */}
      <Card>
        <Text style={styles.sectionTitle}>Predicción USD (6h)</Text>
        <LineChart
          data={chartData}
          width={300}
          height={200}
          chartConfig={{
            backgroundColor: '#ffffff',
            backgroundGradientFrom: '#ffffff',
            backgroundGradientTo: '#ffffff',
            decimalPlaces: 4,
            color: (opacity = 1) => `rgba(134, 65, 244, ${opacity})`,
            labelColor: (opacity = 1) => `rgba(0, 0, 0, ${opacity})`,
          }}
          bezier
          style={styles.chart}
        />
      </Card>

      {/* Acciones Rápidas */}
      <View style={styles.actions}>
        <Button
          title="Nueva Transacción"
          onPress={() => navigation.navigate('Transaction')}
          buttonStyle={[styles.actionButton, styles.primaryButton]}
        />
        <Button
          title="Ver Reportes"
          onPress={() => navigation.navigate('Reports')}
          buttonStyle={[styles.actionButton, styles.secondaryButton]}
        />
      </View>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f5f5',
  },
  alertCard: {
    backgroundColor: '#ffebee',
    borderColor: '#ef5350',
  },
  alertHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  alertTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#c62828',
  },
  alertText: {
    color: '#c62828',
    marginVertical: 2,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    marginBottom: 15,
  },
  ratesGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'space-between',
  },
  rateItem: {
    width: '48%',
    padding: 10,
    backgroundColor: '#f8f8f8',
    borderRadius: 8,
    marginBottom: 10,
  },
  currency: {
    fontSize: 16,
    fontWeight: 'bold',
    marginBottom: 5,
  },
  rateLabel: {
    fontSize: 12,
    color: '#666',
  },
  rateValue: {
    fontSize: 14,
    fontWeight: '600',
    marginBottom: 5,
  },
  chart: {
    marginVertical: 8,
    borderRadius: 16,
  },
  actions: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginVertical: 20,
  },
  actionButton: {
    paddingHorizontal: 30,
    paddingVertical: 12,
    borderRadius: 25,
  },
  primaryButton: {
    backgroundColor: '#6366f1',
  },
  secondaryButton: {
    backgroundColor: '#64748b',
  },
});

export default HomeScreen;
```

## 9. Configuración de Despliegue

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: forex_erp
      POSTGRES_USER: forex_user
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  backend:
    build: ./backend
    command: gunicorn core.wsgi:application --bind 0.0.0.0:8000
    volumes:
      - ./backend:/app
      - static_volume:/app/static
      - media_volume:/app/media
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      - postgres
      - redis

  celery:
    build: ./backend
    command: celery -A core worker -l info
    volumes:
      - ./backend:/app
    env_file:
      - .env
    depends_on:
      - postgres
      - redis

  celery-beat:
    build: ./backend
    command: celery -A core beat -l info
    volumes:
      - ./backend:/app
    env_file:
      - .env
    depends_on:
      - postgres
      - redis

  frontend:
    build: ./frontend
    ports:
      - "3000:80"
    depends_on:
      - backend

  nginx:
    image: nginx:alpine
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - static_volume:/static
      - media_volume:/media
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - backend
      - frontend

volumes:
  postgres_data:
  static_volume:
  media_volume:
```

### Configuración de Celery para Tareas Asíncronas

```python
# backend/core/celery.py
from celery import Celery
from celery.schedules import crontab
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

app = Celery('forex_erp')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Tareas programadas
app.conf.beat_schedule = {
    'update-exchange-rates': {
        'task': 'rates.tasks.update_official_rates',
        'schedule': crontab(minute='*/30'),  # Cada 30 minutos
    },
    'train-prediction-models': {
        'task': 'predictions.tasks.train_models',
        'schedule': crontab(hour=2, minute=0),  # 2 AM diario
    },
    'generate-daily-reports': {
        'task': 'reports.tasks.generate_daily_report',
        'schedule': crontab(hour=23, minute=30),  # 11:30 PM
    },
    'check-inventory-levels': {
        'task': 'inventory.tasks.check_stock_levels',
        'schedule': crontab(minute='*/15'),  # Cada 15 minutos
    },
    'backup-database': {
        'task': 'core.tasks.backup_database',
        'schedule': crontab(hour='*/6'),  # Cada 6 horas
    },
}
```

### Scripts de Backup

```python
# backend/core/backup.py
import os
import boto3
from datetime import datetime
from django.conf import settings
import subprocess

class BackupManager:
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )
        self.bucket_name = settings.BACKUP_BUCKET
    
    def backup_database(self):
        """Realiza backup de la base de datos"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'backup_db_{timestamp}.sql'
        
        # Generar dump de PostgreSQL
        command = [
            'pg_dump',
            f'--dbname={settings.DATABASES["default"]["NAME"]}',
            f'--username={settings.DATABASES["default"]["USER"]}',
            f'--host={settings.DATABASES["default"]["HOST"]}',
            '--no-password',
            f'--file={filename}'
        ]
        
        subprocess.run(command, env={'PGPASSWORD': settings.DATABASES['default']['PASSWORD']})
        
        # Subir a S3
        self.upload_to_s3(filename)
        
        # Eliminar archivo local
        os.remove(filename)
        
        return f's3://{self.bucket_name}/{filename}'
    
    def backup_media_files(self):
        """Backup de archivos media"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'backup_media_{timestamp}.tar.gz'
        
        # Comprimir directorio media
        subprocess.run([
            'tar', '-czf', filename, settings.MEDIA_ROOT
        ])
        
        # Subir a S3
        self.upload_to_s3(filename)
        
        # Eliminar archivo local
        os.remove(filename)
    
    def upload_to_s3(self, filename):
        """Sube archivo a S3"""
        self.s3_client.upload_file(
            filename,
            self.bucket_name,
            f'forex-erp/{filename}'
        )
```

## 10. Documentación de API

### Endpoints Principales

```yaml
# api-documentation.yml
openapi: 3.0.0
info:
  title: Forex ERP API
  version: 1.0.0
  description: API para Sistema de Casa de Cambio

paths:
  /api/auth/login/:
    post:
      summary: Autenticación de usuario
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                username:
                  type: string
                password:
                  type: string
                pin:
                  type: string
      responses:
        200:
          description: Token de acceso
          content:
            application/json:
              schema:
                type: object
                properties:
                  access:
                    type: string
                  refresh:
                    type: string

  /api/rates/current/:
    get:
      summary: Obtiene tasas de cambio actuales
      parameters:
        - name: currency
          in: query
          schema:
            type: string
      responses:
        200:
          description: Tasas actuales
          content:
            application/json:
              schema:
                type: object
                properties:
                  USD:
                    type: object
                    properties:
                      buy:
                        type: number
                      sell:
                        type: number

  /api/transactions/:
    post:
      summary: Registra nueva transacción
      security:
        - bearerAuth: []
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Transaction'
      responses:
        201:
          description: Transacción creada
          content:
            application/json:
              schema:
                type: object
                properties:
                  transaction:
                    $ref: '#/components/schemas/Transaction'
                  receipt_url:
                    type: string

  /api/predictions/current/:
    get:
      summary: Predicciones de tasas de cambio
      parameters:
        - name: pair
          in: query
          schema:
            type: string
            default: USD/BOB
      responses:
        200:
          description: Predicciones para las próximas 24 horas

components:
  schemas:
    Transaction:
      type: object
      required:
        - transaction_type
        - customer_id
        - currency_from
        - amount_from
        - exchange_rate
        - payment_method
      properties:
        transaction_type:
          type: string
          enum: [BUY, SELL]
        customer_id:
          type: integer
        currency_from:
          type: string
        amount_from:
          type: number
        exchange_rate:
          type: number
        payment_method:
          type: string
          enum: [CASH, TRANSFER, QR]
```

## Consideraciones de Seguridad

1. **Autenticación de dos factores** para operaciones sensibles
2. **Encriptación de datos** sensibles en la base de datos
3. **Logs de auditoría** para todas las transacciones
4. **Límites de rate** en las APIs
5. **Validación estricta** de entrada de datos
6. **Backups automáticos** cifrados
7. **Monitoreo de actividad** sospechosa
8. **Cumplimiento normativo** con regulaciones financieras bolivianas

## Próximos Pasos para Implementación

1. **Configurar entorno de desarrollo**
2. **Implementar modelos de base de datos**
3. **Desarrollar APIs REST**
4. **Entrenar modelos de ML con datos históricos**
5. **Construir interfaz de usuario**
6. **Realizar pruebas exhaustivas**
7. **Configurar infraestructura de producción**
8. **Capacitar usuarios**
9. **Desplegar en fases (piloto → producción)**
10. **Monitorear y optimizar**

Este sistema está diseñado para ser escalable, seguro y fácil de mantener, permitiendo el crecimiento futuro hacia servicios adicionales como remesas y asesoría financiera.