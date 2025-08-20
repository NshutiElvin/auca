from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path("ws/notifications/", consumers.NotificationConsumer.as_asgi()),
      path("ws/exams/", consumers.NotificationConsumer.as_asgi()),
]




        
        
