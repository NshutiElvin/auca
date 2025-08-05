import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.layers import get_channel_layer

class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if user.is_authenticated:
            self.user_group = f"user_{user.id}_notification"
            self.broadcast_group = "broadcast_notifications"

            await self.channel_layer.group_add(self.user_group, self.channel_name)
            await self.channel_layer.group_add(self.broadcast_group, self.channel_name)

            await self.accept()
        else:
            await self.close()

    async def disconnect(self, close_code):
        user = self.scope["user"]
        if user.is_authenticated:
            await self.channel_layer.group_discard(self.user_group, self.channel_name)
            await self.channel_layer.group_discard(self.broadcast_group, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        message = data.get("message")
        broadcast = data.get("broadcast", False)  

        channel_layer = get_channel_layer()

        if broadcast:
            await channel_layer.group_send(
                self.broadcast_group,
                {
                    "type": "send_notification",
                    "message": message
                }
            )
        else:
            await channel_layer.group_send(
                self.user_group,
                {
                    "type": "send_notification",
                    "message": message
                }
            )

    async def send_notification(self, event):
        message = event["message"]
        await self.send(text_data=json.dumps({
            "message": message
        }))
