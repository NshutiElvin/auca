from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import ClaimResponseViewSet, StudentClaimViewSet

router = DefaultRouter()
router.register(r'claims', StudentClaimViewSet, basename='studentclaim')
router.register(r'responses', ClaimResponseViewSet, basename='claimresponse')

urlpatterns = [
    path('', include(router.urls)),
]