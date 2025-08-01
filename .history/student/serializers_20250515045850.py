from rest_framework import serializers
 
from django.contrib.auth import get_user_model

from departments.models import Department
from departments.serializers import DepartmentSerializer
from .models import Student


User = get_user_model()
class StudentSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    department=DepartmentSerializer(read_only=True)
    department_id= serializers.PrimaryKeyRelatedField(
          queryset=Department.objects.all(), source='department', write_only=True

    )

    class Meta:
        model = Student
        fields = ['id', 'user', 'reg_no', 'department', "department_id"]
        read_only_fields = ['id', 'user']
