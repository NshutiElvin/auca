from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path("ws/notifications/", consumers.NotificationConsumer.as_asgi()),
    # Was wired to NotificationConsumer — connecting here joined the
    # notification groups, not user_{id}_exams/broadcast_exams, so nothing
    # sent via send_exam_data (type "send_exam_data") could ever be
    # delivered: NotificationConsumer has no send_exam_data handler and
    # never subscribes to the exams groups regardless of which URL was used
    # to connect.
    path("ws/exams/", consumers.RealTimeExamDataConsumer.as_asgi()),
]




        
        
