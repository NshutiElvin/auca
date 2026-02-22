from django.urls import path
from .views import TimetablePDFView

urlpatterns = [
    path('', TimetablePDFView.as_view(), name='timetable-pdf'),
]