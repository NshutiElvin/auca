from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
from django.contrib.auth.models import Permission
class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        user._assign_default_permissions()
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'admin')
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(email, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = (
        ('student', 'Student'),
        ('instructor', 'instructor'),
        ('admin', 'Admin'),
    )
    
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='student')
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    user_permissions = models.ManyToManyField(
        Permission,
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name="custom_user_permissions",
        related_query_name="user",
    )
    objects = UserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    
    def __str__(self):
        return self.email
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    def _assign_default_permissions(self):
        """Assign default permissions based on user role"""
        from django.contrib.auth.models import Permission
        
        # Define default permissions for each role
        default_permissions = {
            'student': [
                'view_student', 'change_student',  # Example permissions
            ],
            'instructor': [
                'view_student', 'change_student', 'view_course', 'change_course',
            ],
            'teacher': [
                'view_student', 'change_student', 'view_course', 'change_course',
                'add_assignment', 'change_assignment',
            ],
            'admin': [
                # Admins typically get all permissions via is_staff/is_superuser
            ]
        }
        
        if self.role in default_permissions:
            for perm_codename in default_permissions[self.role]:
                try:
                    app_label, codename = perm_codename.split('.')
                    permission = Permission.objects.get(
                        content_type__app_label=app_label,
                        codename=codename
                    )
                    self.user_permissions.add(permission)
                except (ValueError, Permission.DoesNotExist):
                    # Skip if permission doesn't exist or format is wrong
                    continue
    
    def get_permissions_list(self):
        """Return list of permission codenames for the user"""
        return list(self.user_permissions.values_list('codename', flat=True))
    
    def get_all_permissions(self):
        """Override to include both group and user permissions"""
        permissions = super().get_all_permissions()
        # Add any custom logic if needed
        return permissions