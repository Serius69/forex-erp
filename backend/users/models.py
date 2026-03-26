# users/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.contrib.auth.hashers import make_password, check_password
import pyotp # type: ignore
import qrcode
from io import BytesIO
import base64

class Branch(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=10, unique=True)
    address = models.TextField()
    phone = models.CharField(max_length=20)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Sucursal'
        verbose_name_plural = 'Sucursales'
    
    def __str__(self):
        return self.name

class User(AbstractUser):
    ROLE_CHOICES = [
        ('ADMIN', 'Administrador'),
        ('SUPERVISOR', 'Supervisor'),
        ('CASHIER', 'Cajero'),
    ]
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='CASHIER')
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True)
    pin = models.CharField(max_length=128, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    two_factor_secret = models.CharField(max_length=32, blank=True)
    is_two_factor_enabled = models.BooleanField(default=False)
    
    class Meta:
        verbose_name = 'Usuario'
        verbose_name_plural = 'Usuarios'
    
    def set_pin(self, raw_pin):
        """Establece el PIN del usuario"""
        self.pin = make_password(raw_pin)
        self.save()
    
    def check_pin(self, raw_pin):
        """Verifica el PIN del usuario"""
        return check_password(raw_pin, self.pin)
    
    def generate_two_factor_secret(self):
        """Genera secret para 2FA"""
        secret = pyotp.random_base32()
        self.two_factor_secret = secret
        self.save()
        return secret
    
    def get_two_factor_qr_code(self):
        """Genera código QR para 2FA"""
        if not self.two_factor_secret:
            self.generate_two_factor_secret()
        
        provisioning_uri = pyotp.totp.TOTP(self.two_factor_secret).provisioning_uri(
            name=self.email,
            issuer_name='Casa de Cambio ERP'
        )
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, 'PNG')
        buffer.seek(0)
        
        return base64.b64encode(buffer.getvalue()).decode()
    
    def verify_two_factor_token(self, token):
        """Verifica token 2FA"""
        if not self.two_factor_secret:
            return False
        
        totp = pyotp.TOTP(self.two_factor_secret)
        return totp.verify(token, valid_window=1)

class UserActivity(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities')
    action = models.CharField(max_length=100)
    details = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField()
    user_agent = models.CharField(max_length=200)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Actividad de Usuario'
        verbose_name_plural = 'Actividades de Usuario'