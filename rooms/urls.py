from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import (
    RoomViewSet, RoomAllocationSwitchViewSet, RoomOutOfServiceViewSet
)

router = DefaultRouter()
# RoomViewSet is registered at the root prefix ('') with a catch-all
# `<pk>/` detail route — any viewset registered AFTER it gets silently
# shadowed (e.g. "room-allocation/" was resolving to
# RoomViewSet.retrieve(pk="room-allocation") instead of
# RoomAllocationSwitchViewSet, confirmed via Django's URL resolver).
# More specific prefixes must be registered first.
router.register(r'room-allocation', RoomAllocationSwitchViewSet)
router.register(r'room-out-of-service', RoomOutOfServiceViewSet)
router.register(r'', RoomViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
