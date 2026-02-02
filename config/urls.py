from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import ConfigViewSet

router = DefaultRouter()
router.register(r'', ConfigViewSet, basename='config')

urlpatterns = [
    path('', include(router.urls)),
]