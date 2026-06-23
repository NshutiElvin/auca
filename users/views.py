from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import (
    UserSerializer,
    CustomTokenObtainPairSerializer,
    PasswordChangeSerializer,
)
from .permissions import IsAdmin, IsModerator
from .validators import get_password_strength
from rest_framework.permissions import AllowAny
from django.contrib.auth.models import Permission
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import User, UserOtp
from notifications.utils import send_mail

import pprint


class CustomTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        refresh_token = request.COOKIES.get("refresh_token")
        if refresh_token is None:
            return Response(
                {"detail": "Refresh token not found in cookies."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        request.data["refresh"] = refresh_token
        response = super().post(request, *args, **kwargs)

        if response.status_code == status.HTTP_200_OK:
            try:
                token = RefreshToken(refresh_token)
                user_id = token.payload.get("user_id")

                if user_id:
                    user = User.objects.get(id=user_id)

                    if not user.is_active:
                        response.delete_cookie("refresh_token")
                        return Response(
                            {
                                "success": False,
                                "message": "Account is deactivated. Please contact administrator.",
                            },
                            status=status.HTTP_401_UNAUTHORIZED,
                        )

                    if hasattr(user, "get_permissions_list"):
                        user_permissions = user.get_permissions_list()
                    else:
                        if user.is_superuser:
                            user_permissions = list(
                                Permission.objects.values_list("codename", flat=True)
                            )
                        else:
                            user_perms = user.user_permissions.values_list(
                                "codename", flat=True
                            )
                            group_perms = Permission.objects.filter(
                                group__user=user
                            ).values_list("codename", flat=True)
                            user_permissions = list(set(user_perms) | set(group_perms))

                    response.data["permissions"] = user_permissions

            except User.DoesNotExist:
                response.delete_cookie("refresh_token")
                response.data["permissions"] = []
            except Exception as e:
                print(f"Error getting user permissions during refresh: {str(e)}")
                response.data["permissions"] = []

        return response


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        try:
            serializer.is_valid(raise_exception=True)
            user = serializer.user
        except Exception:
            return Response(
                {"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED
            )

        response = super().post(request, *args, **kwargs)

        if response.status_code == status.HTTP_200_OK:
            refresh_token = response.data.get("refresh")
            user_permissions = user.get_permissions_list()

            response.set_cookie(
                key="refresh_token",
                value=refresh_token,
                httponly=True,
                secure=True,
                samesite="None",
                max_age=60 * 60 * 24,
            )
            response.data.pop("refresh", None)
            response.data["permissions"] = user_permissions

            # Generate and send OTP immediately after successful login
            try:
                otp_obj, _ = UserOtp.objects.get_or_create(user=user)
                otp_code = otp_obj.generate_otp()
                send_mail(
                    subject="Your One-Time Password",
                    message=(
                        f"Hello {user.get_full_name() or user.email},\n\n"
                        f"Your OTP code is: {otp_code}\n\n"
                        f"It will expire in {UserOtp.OTP_EXPIRY_MINUTES} minutes.\n"
                        "If you did not request this, please ignore this email."
                    ),
                    from_email=None,
                    recipient_list=[user.email],
                    fail_silently=False,
                )
            except Exception as e:
                print(f"Error sending OTP email: {str(e)}")

        return response



class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["id", "email", "first_name", "last_name"]

    def get_permissions(self):
        if self.action == "logout":
            permission_classes = [permissions.IsAuthenticated]
        elif self.action == "create":
            permission_classes = [permissions.AllowAny]
        elif self.action in ["list", "retrieve"]:
            permission_classes = [permissions.IsAuthenticated]
        elif self.action in ["check_password_strength"]:
            permission_classes = [permissions.AllowAny]
        elif self.action in ["change_password", "verify_otp"]:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [IsAdmin]
        return [permission() for permission in permission_classes]

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        data.pop("permissions", None)
        pprint.pprint(data)
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": "User created successfully",
            },
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(
                {
                    "success": True,
                    "data": serializer.data,
                    "message": "Fetched successfully",
                }
            )

        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": "Fetched successfully",
            }
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": "User fetched successfully",
            }
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        data = request.data.copy()
        pprint.pprint(data)
        data.pop("permissions", None)
        serializer = self.get_serializer(instance, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": "User updated successfully",
            }
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(
            {"success": True, "message": "User deleted successfully"},
            status=status.HTTP_204_NO_CONTENT,
        )

    @action(
        detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated]
    )
    def profile(self, request):
        serializer = self.get_serializer(request.user)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": "Profile fetched successfully",
            }
        )

    @action(
        detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated]
    )
    def user_permissions(self, request):
        all_permissions = Permission.objects.all()
        known_models = [
            "course",
            "department",
            "enrollment",
            "student",
            "exam",
            "studentexam",
            "unscheduledexam",
            "studentclaim",
            "claimresponse",
            "room",
        ]
        data = [
            {
                "codename": perm.codename,
                "name": perm.name,
                "model": perm.content_type.model,
            }
            for perm in all_permissions
            if perm.content_type.model in known_models
        ]
        return Response(
            {"success": True, "data": data, "message": "Permissions fetched successfully"}
        )

    @action(detail=False, methods=["post"], permission_classes=[permissions.AllowAny])
    def check_password_strength(self, request):
        password = request.data.get("password")
        if not password:
            return Response(
                {"success": False, "message": "Password is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user if request.user.is_authenticated else None
        strength_info = get_password_strength(password, user)
        return Response(
            {
                "success": True,
                "data": strength_info,
                "message": "Password strength checked successfully",
            }
        )

    @action(
        detail=False, methods=["post"], permission_classes=[permissions.IsAuthenticated]
    )
    def change_password(self, request):
        serializer = PasswordChangeSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {
                "success": True,
                "data": {"password_strength": serializer.data.get("password_strength")},
                "message": "Password changed successfully",
            }
        )

    @action(
        detail=False, methods=["post"], permission_classes=[permissions.IsAuthenticated]
    )
    def verify_otp(self, request):
        """Verify the OTP submitted by the authenticated user."""
        otp_input = request.data.get("otp", "").strip()
        if not otp_input:
            return Response(
                {"success": False, "message": "OTP is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            otp_obj = UserOtp.objects.get(user=request.user)
        except UserOtp.DoesNotExist:
            return Response(
                {"success": False, "message": "No OTP found. Please request a new one."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if otp_obj.is_verified:
            return Response(
                {"success": False, "message": "OTP has already been used. Please request a new one."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if otp_obj.is_expired():
            return Response(
                {"success": False, "message": "OTP has expired. Please request a new one."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if otp_obj.otp != otp_input:
            return Response(
                {"success": False, "message": "Invalid OTP."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otp_obj.is_verified = True
        otp_obj.save(update_fields=["is_verified"])

        return Response(
            {"success": True, "message": "OTP verified successfully."}
        )

    @action(
        detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated]
    )
    def instructors(self, request):
        instructors = User.objects.filter(role="instructor")
        serializer = self.get_serializer(instructors, many=True)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": "Instructors fetched successfully",
            }
        )

    @action(
        detail=False, methods=["post"], permission_classes=[permissions.IsAuthenticated]
    )
    def logout(self, request):
        try:
            response = Response({"success": True, "message": "Logged out successfully"})

            refresh_token = request.COOKIES.get("refresh_token")
            if refresh_token:
                try:
                    token = RefreshToken(refresh_token)
                    token.blacklist()
                except Exception as e:
                    print(f"Error blacklisting refresh token: {str(e)}")
                response.delete_cookie("refresh_token")

            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                access_token_str = auth_header.split(" ")[1]
                try:
                    outstanding_token = OutstandingToken.objects.get(
                        token=access_token_str
                    )
                    BlacklistedToken.objects.get_or_create(token=outstanding_token)
                except OutstandingToken.DoesNotExist:
                    pass
                except Exception as e:
                    print(f"Error blacklisting access token: {str(e)}")

            return response

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=400)