from rest_framework import serializers
 
from django.contrib.auth import get_user_model
from .models import Student


User = get_user_model()
class StudentSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField()

    fields = ['id', 'user', 'reg_no', 'department']
    read_only_fields = ['id', 'user']

    class Meta:
        model = Student
        fields = '__all__'