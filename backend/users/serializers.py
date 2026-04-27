import re
from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import User, Branch, UserActivity
from tenants.serializers import CompanyPublicSerializer


def _validate_password_strength(value: str) -> str:
    """OWASP: 8+ chars, uppercase, digit, special symbol."""
    if len(value) < 8:
        raise serializers.ValidationError('Mínimo 8 caracteres.')
    if not re.search(r'[A-Z]', value):
        raise serializers.ValidationError('Debe incluir al menos una mayúscula.')
    if not re.search(r'\d', value):
        raise serializers.ValidationError('Debe incluir al menos un número.')
    if not re.search(r'[!@#$%^&*()\-_=+\[\]{};:\'",.<>?/\\|`~]', value):
        raise serializers.ValidationError('Debe incluir al menos un símbolo especial.')
    return value


class BranchSerializer(serializers.ModelSerializer):
    company_name = serializers.SerializerMethodField()

    class Meta:
        model  = Branch
        fields = [
            'id', 'name', 'code', 'city', 'address', 'phone',
            'is_main', 'is_active', 'company_id', 'company_name', 'created_at',
        ]

    def get_company_name(self, obj):
        return obj.company.name if obj.company_id else None


class UserSerializer(serializers.ModelSerializer):
    branch     = BranchSerializer(read_only=True)
    branch_id  = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.all(), source='branch', write_only=True,
        required=False, allow_null=True,
    )
    company    = CompanyPublicSerializer(read_only=True)
    company_id = serializers.PrimaryKeyRelatedField(
        source='company',
        read_only=True,
    )

    class Meta:
        model  = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'email',
            'role', 'branch', 'branch_id', 'company', 'company_id', 'phone',
            'is_two_factor_enabled', 'is_active', 'is_verified',
            'date_joined', 'last_login',
        ]
        read_only_fields = ['date_joined', 'last_login', 'is_verified', 'company', 'company_id']

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = super().create(validated_data)
        if password:
            user.set_password(password)
            user.save()
        return user


class UserCreateSerializer(serializers.ModelSerializer):
    password  = serializers.CharField(write_only=True, min_length=8)
    branch_id = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.all(), source='branch', required=False, allow_null=True,
    )

    class Meta:
        model  = User
        fields = ['username', 'first_name', 'last_name', 'email',
                  'password', 'role', 'branch_id', 'phone']

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class SignupSerializer(serializers.Serializer):
    email            = serializers.EmailField()
    username         = serializers.CharField(min_length=3, max_length=150, required=False, allow_blank=True)
    first_name       = serializers.CharField(max_length=150, required=False, default='')
    last_name        = serializers.CharField(max_length=150, required=False, default='')
    password         = serializers.CharField(write_only=True)
    password_confirm = serializers.CharField(write_only=True)

    def validate_email(self, value):
        value = value.lower().strip()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('Este email ya está registrado.')
        return value

    def validate_username(self, value):
        value = value.strip()
        if value and User.objects.filter(username=value).exists():
            raise serializers.ValidationError('Este nombre de usuario ya está en uso.')
        return value

    def validate_password(self, value):
        return _validate_password_strength(value)

    def validate(self, data):
        if data['password'] != data.pop('password_confirm'):
            raise serializers.ValidationError({'password_confirm': 'Las contraseñas no coinciden.'})
        return data

    def create(self, validated_data):
        email    = validated_data['email']
        username = (validated_data.get('username') or '').strip() or email.split('@')[0]

        base    = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f'{base}{counter}'
            counter += 1

        # Assign to default company if it exists
        from tenants.models import Company
        default_company = Company.objects.filter(is_active=True).order_by('id').first()

        return User.objects.create_user(
            username    = username,
            email       = email,
            password    = validated_data['password'],
            first_name  = validated_data.get('first_name', ''),
            last_name   = validated_data.get('last_name', ''),
            role        = 'CASHIER',
            is_active   = True,
            is_verified = False,
            company     = default_company,
        )


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(username=data['username'], password=data['password'])
        if not user:
            raise serializers.ValidationError('Credenciales incorrectas')
        if not user.is_active:
            raise serializers.ValidationError('Usuario inactivo')
        data['user'] = user
        return data


class UserActivitySerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField()

    class Meta:
        model  = UserActivity
        fields = ['id', 'user', 'action', 'details',
                  'ip_address', 'user_agent', 'timestamp']
        read_only_fields = fields
