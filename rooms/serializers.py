from rest_framework import serializers
from rooms.models import Room, RoomAllocationSwitch

from django.contrib.auth import get_user_model

User = get_user_model()
class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = '__all__'
class RoomAllocationSwitchSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomAllocationSwitch
        fields = '__all__'