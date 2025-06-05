from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import User, Branch, UserActivity

class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = '__all__'

class UserSerializer(serializers.ModelSerializer):
    branch = BranchSerializer(read_only=True)
    branch_id = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.all(),
        source='branch',
        write_only=True
    )
    
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'role', 'branch', 'branch_id', 'phone', 'is_active',
            'is_two_factor_enabled', 'date_joined'
        ]
        read_only_fields = ['id', 'date_joined']
    
    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = super().create(validated_data)
        if password:
            user.set_password(password)
            user.save()
        return user

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()
    pin = serializers.CharField(required=False)
    two_factor_token = serializers.CharField(required=False)
    
    def validate(self, attrs):
        username = attrs.get('username')
        password = attrs.get('password')
        
        if username and password:
            user = authenticate(username=username, password=password)
            
            if not user:
                raise serializers.ValidationError('Credenciales inválidas')
            
            if not user.is_active:
                raise serializers.ValidationError('Usuario inactivo')
            
            # Verificar 2FA si está habilitado
            if user.is_two_factor_enabled:
                token = attrs.get('two_factor_token')
                if not token or not user.verify_two_factor_token(token):
                    raise serializers.ValidationError('Token 2FA inválido')
            
            attrs['user'] = user
            return attrs
        
        raise serializers.ValidationError('Debe incluir username y password')

class UserActivitySerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = UserActivity
        fields = '__all__'