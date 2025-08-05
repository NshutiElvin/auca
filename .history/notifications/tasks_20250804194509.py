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
            f"user_{user_id}", {
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








def find_collatz_sequence(n):
    
    longest_len=0
    longest_x=None
    x=n
    while x<n:
        sequence=[]
        y=x
        while True:
            if y%2==0:
                num=y/2
                sequence.append(num)
                y=num
            else:
                num= 3*y+1
                sequence.append(num)
                y=num
            if y==1:
                break
        if not longest_x and longest_len==0:
            longest_x=y
            longest_len= len(sequence)
        else:
            if len(sequence)>longest_len:
                longest_x=y
                longest_len= len(sequence)
                
        n-=1
                
        

        return seaquence
