from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import (
    EnrollmentViewSet,
)

router = DefaultRouter()
 
router.register('', EnrollmentViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
