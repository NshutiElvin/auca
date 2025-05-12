from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .validators import get_password_strength

User = get_user_model()

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Add custom claims
        token['email'] = user.email
        token['role'] = user.role
        return token

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password_strength = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = User
        fields = ('id', 'email', 'first_name', 'last_name', 'password', 'password_strength', 'role')
        extra_kwargs = {
            'password': {'write_only': True}
        }
    
    def get_password_strength(self, obj):
        """
        Calculate password strength when reading the object
        """
        # Only return strength for password_confirmation during creation
        password = self.initial_data.get('password', None) if hasattr(self, 'initial_data') else None
        
        if password:
            return get_password_strength(password)
        return None
    
    def validate_password(self, value):
        """
        Check password strength during validation
        """
        # First run the default validators
        validate_password(value)
        
        # Then check strength
        strength_info = get_password_strength(value)
        
        # If password is too weak, raise validation error
        if strength_info['score'] < 40:  # Require at least medium strength
            raise serializers.ValidationError(
                f"Password is too weak (strength: {strength_info['strength']}). "
                f"Please address these issues: {', '.join(strength_info['feedback']['warnings'] + strength_info['feedback']['suggestions'])}"
            )
        
        return value
    
    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        return user
    
    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        user = super().update(instance, validated_data)
        
        if password:
            user.set_password(password)
            user.save()
        
        return user


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, validators=[validate_password])
    password_strength = serializers.SerializerMethodField(read_only=True)
    
    def get_password_strength(self, obj):
        password = self.initial_data.get('new_password', None)
        if password:
            return get_password_strength(password)
        return None
    
    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect")
        return value
    
    def validate_new_password(self, value):
        """
        Check password strength during validation
        """
        # First run the default validators
        validate_password(value)
        
        # Then check strength
        strength_info = get_password_strength(value, self.context['request'].user)
        
        # If password is too weak, raise validation error
        if strength_info['score'] < 40:  # Require at least medium strength
            raise serializers.ValidationError(
                f"Password is too weak (strength: {strength_info['strength']}). "
                f"Please address these issues: {', '.join(strength_info['feedback']['warnings'] + strength_info['feedback']['suggestions'])}"
            )
        
        return value
    
    def save(self):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user