from rest_framework import serializers

from rooms.serializers import LocationSerializer
from .models import Department
from django.contrib.auth import get_user_model

User = get_user_model()

class DepartmentSerializer(serializers.ModelSerializer):
    location= LocationSerializer(read_only=True)
    class Meta:
        model = Department
        fields =  ['id', 'code', 'name', 'location']