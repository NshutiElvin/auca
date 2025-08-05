from celery import shared_task
from django.contrib.auth import get_user_model
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

@shared_task
def send_notification( message,user_id=None, broadcast=False):
    user = get_user_model().objects.get(id=user_id)
 
    if user and not broadcast:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}_notification", {
                "type": "send_notification",
                "message": message
            }
        )
    elif broadcast:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "broadcast_notifications", {
                "type": "send_notification",
                "message": message
            }
        )









