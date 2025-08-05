from rest_framework import serializers
from .models import Notification
from django.contrib.auth import get_user_model

User = get_user_model()

class NotificationSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    
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
        read_only_fields = ['id', 'created_at', 'read_at']

    