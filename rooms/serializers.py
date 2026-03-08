from rest_framework import serializers
from rooms.models import Location, Room, RoomAllocationSwitch

from django.contrib.auth import get_user_model

User = get_user_model()

class RoomAllocationSwitchSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomAllocationSwitch
        fields = '__all__'

class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model =Location
        fields = '__all__'

class RoomSerializer(serializers.ModelSerializer):
    location= LocationSerializer(read_only=True)
    class Meta:
        model = Room
        fields = '__all__'