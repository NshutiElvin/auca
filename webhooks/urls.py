from django.urls import path
from .views import CheckAndUpdateExamsWebhookView

urlpatterns = [
    path('check-exams/', CheckAndUpdateExamsWebhookView.as_view(), name='check-exams-webhook'),
]