from rest_framework import serializers

from rooms.serializers import LocationSerializer
from rooms.models import Location
from .models import Department
from django.contrib.auth import get_user_model

User = get_user_model()

class DepartmentSerializer(serializers.ModelSerializer):
    location = LocationSerializer(read_only=True)
    location_id = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), source='location',
        write_only=True, required=False, allow_null=True,
    )
    class Meta:
        model = Department
        fields = ['id', 'code', 'name', 'location', 'location_id']