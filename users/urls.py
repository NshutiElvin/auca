from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import UserViewSet, CustomTokenObtainPairView, CustomTokenRefreshView, SendOtpView

router = DefaultRouter()
router.register(r'', UserViewSet)

urlpatterns = [
    path('token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('token/otp/send/', SendOtpView.as_view(), name='token_otp_send'),
    path('', include(router.urls)),
]