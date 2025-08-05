from rest_framework import serializers
from .models import Notification
from django.contrib.auth import get_user_model

User = get_user_model()

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            'id',
            'user',
            'title',
            'message',
            'created_at',
            'is_read',
            'read_at',
        ]
        read_only_fields = ['id', 'user', 'created_at', 'read_at']

class MarkAsReadSerializer(serializers.Serializer):
    is_read = serializers.BooleanField(required=True)