from celery import shared_task
from django.contrib.auth import get_user_model
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.mail import send_mail
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


@shared_task
def  send_email_task( subject=None, message=None, from_email=None, recipient_list=None):

      send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=recipient_list,
        )








