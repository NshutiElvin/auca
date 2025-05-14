from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import (
     
    RoomViewSet, RoomAllocationSwitchViewSet
  
)

router = DefaultRouter()
router.register(r'', RoomViewSet)
router.register(r'room-allocation', RoomAllocationSwitchViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
