from rest_framework import serializers
 
from django.contrib.auth import get_user_model

from departments.models import Department
from departments.serializers import DepartmentSerializer
from users.serializers import UserSerializer
from .models import Student


User = get_user_model()
class StudentSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    # `user` is a required (non-null) OneToOneField with no writable
    # counterpart before this — POST /api/students/ could never succeed
    # (IntegrityError: user_id may not be NULL). Students are normally
    # created indirectly via UserSerializer.create(), but this endpoint is
    # exposed and admin-only, so it should actually work.
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source='user', write_only=True
    )
    department=DepartmentSerializer(read_only=True)
    department_id= serializers.PrimaryKeyRelatedField(
          queryset=Department.objects.all(), source='department', write_only=True

    )
    useInfo = UserSerializer(read_only=True)

    class Meta:
        model = Student
        fields = ['id', 'user', 'user_id', 'reg_no', 'department', "department_id", "useInfo"]
        read_only_fields = ['id', 'user', 'useInfo']
