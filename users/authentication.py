from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import UserOtp

# The frontend already treats login as two steps — it holds the JWT and
# does not attach it to any request (or commit auth state) until OTP
# verification succeeds (see login-form.tsx). But the backend never
# actually checked that: any valid JWT worked on every endpoint regardless
# of OTP status, making the OTP step purely decorative and bypassable by
# anyone who obtains a token through another route. These are the only
# paths that must stay reachable with a valid-but-not-yet-verified token,
# since completing OTP verification (or logging out) requires one.
OTP_EXEMPT_PATHS = {
    "/api/users/verify_otp/",
    "/api/users/logout/",
    "/api/users/check_password_strength/",
}


class OtpVerifiedJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None

        user, validated_token = result

        if request.path in OTP_EXEMPT_PATHS:
            return result

        otp = UserOtp.objects.filter(user=user).first()
        if not otp or not otp.is_verified:
            raise AuthenticationFailed(
                "OTP verification required.", code="otp_required"
            )

        return result
