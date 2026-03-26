from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import User, Branch, UserActivity


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Branch
        fields = ['id', 'name', 'code', 'address', 'phone', 'is_active', 'created_at']


class UserSerializer(serializers.ModelSerializer):
    branch = BranchSerializer(read_only=True)
    branch_id = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.all(), source='branch', write_only=True,
        required=False, allow_null=True)

    class Meta:
        model  = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'email',
            'role', 'branch', 'branch_id', 'phone',
            'is_two_factor_enabled', 'is_active',
            'date_joined', 'last_login',
        ]
        read_only_fields = ['date_joined', 'last_login']

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
        queryset=Branch.objects.all(), source='branch', required=False, allow_null=True)

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


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(
            username=data['username'],
            password=data['password']
        )
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