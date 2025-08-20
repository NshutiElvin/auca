from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import (
     
    ImportEnrollmentsData
  
)

urlpatterns = [
    path('', ImportEnrollmentsData.as_view(), name='uploads'),
]
