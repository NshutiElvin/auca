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

    def update(self, instance, validated_data):
        # Handle marking as read/unread through the serializer
        is_read = validated_data.get('is_read', instance.is_read)
        
        if is_read and not instance.is_read:
            instance.mark_as_read()
        elif not is_read and instance.is_read:
            instance.mark_as_unread()
        
        return super().update(instance, validated_data)