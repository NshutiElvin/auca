from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .validators import get_password_strength
from rest_framework.permissions import AllowAny
from departments.models import Department
from django.db import transaction
from student.models import Student
from django.utils.translation import gettext_lazy as _
from Admin.models import Admin
from django.conf import settings
from django.contrib.auth.models import Permission
import logging
User = get_user_model()
logger = logging.getLogger(__name__)
class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
   
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['email'] = user.email
        token['role'] = user.role
        token["key"]=settings.ENCRYPTION_KEY
        return token

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, validators=[validate_password])
    password_strength = serializers.SerializerMethodField(read_only=True)
    reg_no = serializers.CharField(write_only=True, required=False)
    department = serializers.PrimaryKeyRelatedField(write_only=True, queryset=Department.objects.all(), required=False)
    user_permissions = serializers.ListField(
    child=serializers.CharField(),
    write_only=True,
    required=False,
    help_text="List of permission codenames to assign to the user"
)
    current_permissions = serializers.ListField(
    child=serializers.CharField(),
    read_only=True,
    source='get_permissions_list'
)
    class Meta:
        model = User
        fields = (
    'id', 'email', 'first_name', 'last_name', 'password', "is_active",
    'password_strength', 'role', 'reg_no', 'department',
    'user_permissions', 'current_permissions'   
)

        extra_kwargs = {
            'password': {'write_only': True},
            'user_permissions': {'write_only': True}
        }
    
    def get_all_permissions(self, obj):
        """Return all permissions (including groups)"""
        return list(obj.get_all_permissions())
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
        # Extract permissions if provided during creation
        permissions_data = validated_data.pop('user_permissions', None)
        
        role = validated_data.get('role')
        if role not in ['admin', 'student', 'instructor', 'teacher']:
            raise serializers.ValidationError("Invalid role. Must be 'admin', 'student', 'instructor', or 'teacher'.")

        reg_no = validated_data.pop('reg_no', None)
        department = validated_data.pop('department', None)
        logging.debug(str(permissions_data))

        with transaction.atomic():
            user = User.objects.create_user(**validated_data)
            
              # Handle permissions update if provided
            if permissions_data is not None:
                user.user_permissions.clear()
                for perm_codename in permissions_data:
                    logging.debug(str(perm_codename))
                    try:
                        permission = Permission.objects.filter(codename=perm_codename).first()
                        user.user_permissions.add(permission)
                    except Permission.DoesNotExist:
                        # Skip if permission doesn't exist
                        continue

            if user.role == 'student':
                if not reg_no or not department:
                    raise serializers.ValidationError("reg_no and department are required for students.")
                try:
                    Student.objects.create(user=user, reg_no=reg_no, department=department)
                except Exception as e:
                    raise serializers.ValidationError(str(e))
            elif user.role == 'admin':
                try:
                    Admin.objects.create(user=user)
                except Exception as e:
                    raise serializers.ValidationError(str(e))
            transaction.on_commit(lambda: logging.debug(f"User {user.id} created successfull"))

        return user
    
    def update(self, instance, validated_data):
    # Extract permissions if provided
        permissions_data = validated_data.pop('user_permissions', None)
        logging.debug(str(permissions_data))
        
        # Use transaction to ensure atomicity
        with transaction.atomic():
            user = super().update(instance, validated_data)
            
            # Handle permissions update if provided
            if permissions_data is not None:
                user.user_permissions.clear()
                for perm_codename in permissions_data:
                    print(perm_codename)
                    try:
                        permission = Permission.objects.filter(codename=perm_codename).first()
                        user.user_permissions.add(permission)
                    except Permission.DoesNotExist:
                        logging.warning(f"Permission {perm_codename} does not exist")
                        continue
            
            transaction.on_commit(lambda: logging.debug(f"User {user.id} update successfull"))
        
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
    
import logging
from django.db import transaction, connection
from django.contrib.auth.models import Permission
from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth.password_validation import validate_password

logger = logging.getLogger(__name__)

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, validators=[validate_password])
    password_strength = serializers.SerializerMethodField(read_only=True)
    reg_no = serializers.CharField(write_only=True, required=False)
    department = serializers.PrimaryKeyRelatedField(write_only=True, queryset=Department.objects.all(), required=False)
    user_permissions = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,
        help_text="List of permission codenames to assign to the user"
    )
    current_permissions = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        source='get_permissions_list'
    )
    
    class Meta:
        model = User
        fields = (
            'id', 'email', 'first_name', 'last_name', 'password', 'is_active',
            'password_strength', 'role', 'reg_no', 'department',
            'user_permissions', 'current_permissions'   
        )
        extra_kwargs = {
            'password': {'write_only': True},
            'user_permissions': {'write_only': True}
        }
    
    def get_all_permissions(self, obj):
        """Return all permissions (including groups)"""
        return list(obj.get_all_permissions())
    
    def get_password_strength(self, obj):
        """
        Calculate password strength when reading the object
        """
        # Use validated_data instead of initial_data for reliability
        if hasattr(self, 'validated_data') and 'password' in self.validated_data:
            return get_password_strength(self.validated_data['password'])
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
    
    def _assign_permissions(self, user, permissions_data):
        """Helper method to assign permissions safely"""
        if not permissions_data:
            return
        
        # Get valid permissions first to minimize database calls
        valid_permissions = Permission.objects.filter(
            codename__in=permissions_data
        )
        
        # Clear existing permissions
        user.user_permissions.clear()
        
        # Add new permissions
        for permission in valid_permissions:
            user.user_permissions.add(permission)
        
        # Log any invalid permission codes
        valid_codenames = set(valid_permissions.values_list('codename', flat=True))
        invalid_codenames = set(permissions_data) - valid_codenames
        
        if invalid_codenames:
            logger.warning(f"Invalid permission codenames: {invalid_codenames}")
    
    def _create_role_profile(self, user, role, reg_no=None, department=None):
        """Helper method to create role-specific profiles"""
        if role == 'student':
            if not reg_no or not department:
                raise serializers.ValidationError("reg_no and department are required for students.")
            Student.objects.create(user=user, reg_no=reg_no, department=department)
            logger.info(f"Student profile created for user {user.id}")
        
        elif role == 'admin':
            Admin.objects.create(user=user)
            logger.info(f"Admin profile created for user {user.id}")
        
        # Add other roles as needed
        elif role in ['instructor', 'teacher']:
            # Handle other roles if they exist
            logger.info(f"No specific profile needed for role: {role}")
    
    def create(self, validated_data):
        """
        Create user with immediate commit and proper error handling
        """
        logger.info("🚀 CREATE started with data: %s", {k: v for k, v in validated_data.items() if k != 'password'})
        
        # Extract related data
        permissions_data = validated_data.pop('user_permissions', [])
        reg_no = validated_data.pop('reg_no', None)
        department = validated_data.pop('department', None)
        role = validated_data.get('role')
        
        # Validate role
        if role not in ['admin', 'student', 'instructor', 'teacher']:
            raise serializers.ValidationError("Invalid role. Must be 'admin', 'student', 'instructor', or 'teacher'.")
        
        # Validate student-specific fields
        if role == 'student' and (not reg_no or not department):
            raise serializers.ValidationError("reg_no and department are required for students.")
        
        try:
            # Create user FIRST without transaction for immediate commit
            user = User.objects.create_user(**validated_data)
            logger.info("✅ User created with ID: %s", user.id)
            
            # Force immediate commit
            connection.commit()
            logger.info("✅ Database commit forced after user creation")
            
            # Verify user exists immediately
            exists = User.objects.filter(id=user.id).exists()
            if not exists:
                raise serializers.ValidationError("User was not persisted to database immediately")
            
            # Now handle permissions and profiles in a transaction
            with transaction.atomic():
                if permissions_data:
                    self._assign_permissions(user, permissions_data)
                    logger.info("✅ Permissions assigned: %s", permissions_data)
                
                # Create role-specific profile
                self._create_role_profile(user, role, reg_no, department)
            
            # Force final commit
            connection.commit()
            logger.info("✅ Final commit completed for user %s", user.id)
            
            # Refresh from database to get all related data
            user.refresh_from_db()
            logger.info("🎉 User creation completed successfully for ID: %s", user.id)
            
            return user
            
        except DjangoValidationError as e:
            logger.error("❌ Validation error during user creation: %s", str(e))
            raise serializers.ValidationError(str(e))
            
        except Exception as e:
            logger.error("❌ Unexpected error during user creation: %s", str(e), exc_info=True)
            
            # Clean up if user was created but something else failed
            if 'user' in locals() and hasattr(user, 'id'):
                try:
                    user.delete()
                    logger.info("🧹 Cleaned up partially created user %s", user.id)
                except Exception as delete_error:
                    logger.error("❌ Failed to clean up user: %s", str(delete_error))
            
            raise serializers.ValidationError(f"User creation failed: {str(e)}")
    
    def update(self, instance, validated_data):
        """
        Update user with immediate commit and proper error handling
        """
        logger.info("🔄 UPDATE started for user %s with data: %s", 
                   instance.id, {k: v for k, v in validated_data.items() if k != 'password'})
        
        # Extract permissions data
        permissions_data = validated_data.pop('user_permissions', None)
        
        try:
            # Handle password separately if provided
            password = validated_data.pop('password', None)
            
            # Update basic fields first
            user = super().update(instance, validated_data)
            
            # Update password if provided
            if password:
                user.set_password(password)
                user.save()
                logger.info("✅ Password updated for user %s", user.id)
            
            # Force immediate commit for basic update
            connection.commit()
            logger.info("✅ Basic update committed for user %s", user.id)
            
            # Handle permissions if provided
            if permissions_data is not None:
                with transaction.atomic():
                    self._assign_permissions(user, permissions_data)
                    logger.info("✅ Permissions updated: %s", permissions_data)
                
                # Commit permissions changes
                connection.commit()
                logger.info("✅ Permissions commit completed for user %s", user.id)
            
            # Refresh from database to ensure we have latest state
            user.refresh_from_db()
            logger.info("🎉 User update completed successfully for ID: %s", user.id)
            
            return user
            
        except DjangoValidationError as e:
            logger.error("❌ Validation error during user update: %s", str(e))
            raise serializers.ValidationError(str(e))
            
        except Exception as e:
            logger.error("❌ Unexpected error during user update: %s", str(e), exc_info=True)
            raise serializers.ValidationError(f"User update failed: {str(e)}")
 