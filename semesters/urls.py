from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import (
    SemesterViewSet,
)

router = DefaultRouter()
router.register(r'', SemesterViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
