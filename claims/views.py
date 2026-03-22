from rest_framework import viewsets, status, permissions
from rest_framework.response import Response

from .models import ClaimResponse, StudentClaim
from .serializers import StudentClaimSerializer, ClaimResponseSerializer
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from student.models import Student
from rest_framework.exceptions import PermissionDenied
from notifications.models import Notification
from notifications.tasks import send_notification, send_email_task
from users.models import User


def _bulk_notify(notifications_data):
    """
    Helper to bulk-create Notification objects and dispatch each via send_notification.

    notifications_data: list of dicts with keys: user_id, title, message
    """
    notification_objects = [
        Notification(user=n["user"], title=n["title"], message=n["message"])
        for n in notifications_data
    ]
    created = Notification.objects.bulk_create(notification_objects)
    for notification in created:
        send_notification(
            {
                "id": notification.id,
                "title": notification.title,
                "message": notification.message,
                "created_at": notification.created_at.isoformat(),
                "is_read": notification.is_read,
                "read_at": notification.read_at.isoformat() if notification.read_at else None,
            },
            notification.user.id,
        )


class BaseViewSet(viewsets.ModelViewSet):
    """
    Base ViewSet to format responses consistently.
    Handles StudentClaim CRUD with notifications sent to relevant parties at each step.
    """

    filter_backends = [DjangoFilterBackend, SearchFilter]

    def _resource_name(self):
        try:
            return getattr(self, "basename")
        except Exception:
            return self.get_queryset().model.__name__.lower()

    # ------------------------------------------------------------------ #
    #  LIST
    # ------------------------------------------------------------------ #
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response({"success": True, "data": serializer.data})

        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": f"{self._resource_name().title()}s fetched successfully",
            }
        )

    # ------------------------------------------------------------------ #
    #  QUERYSET – students only see their own claims
    # ------------------------------------------------------------------ #
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        user_permissions = user.get_permissions_list()
        

        if not user.is_staff and "view_studentclaim" not in user_permissions:
            try:
                student = Student.objects.get(user=user)
                queryset = queryset.filter(student=student)
            except Student.DoesNotExist:
                queryset = StudentClaim.objects.none()

        return queryset

    # ------------------------------------------------------------------ #
    #  RETRIEVE
    # ------------------------------------------------------------------ #
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": f"{self._resource_name().title()} fetched successfully",
            }
        )

    # ------------------------------------------------------------------ #
    #  CREATE – notify all admins a new claim arrived; confirm to student
    # ------------------------------------------------------------------ #
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)

        claim_type = serializer.data.get("claim_type", "N/A")
        description = serializer.data.get("description", "")
        student_name = (
            f"{request.user.first_name} {request.user.last_name}".strip()
            or request.user.username
        )

        notifications_data = []

        # Notify every superuser admin
        for admin in User.objects.filter(is_superuser=True):
            notifications_data.append(
                {
                    "user": admin,
                    "title": f"New Claim Submitted – {claim_type}",
                    "message": (
                        f"Student {student_name} has submitted a new '{claim_type}' claim. "
                        f"Details: {description[:200]}"
                    ),
                }
            )

        # Confirm submission to the student
        notifications_data.append(
            {
                "user": request.user,
                "title": "Your Claim Has Been Submitted",
                "message": (
                    f"Your '{claim_type}' claim has been received and is currently under review. "
                    "You will be notified once there is an update."
                ),
            }
        )

        _bulk_notify(notifications_data)

        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": f"{self._resource_name().title()} created successfully",
            },
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def perform_create(self, serializer):
        try:
            student_instance = Student.objects.get(user=self.request.user)
            serializer.save(student=student_instance)
        except Student.DoesNotExist:
            raise PermissionDenied("No student record found for this user.")

    # ------------------------------------------------------------------ #
    #  UPDATE – notify student of status change; alert other admins
    # ------------------------------------------------------------------ #
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        old_status = instance.status  # capture before save

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        updated_claim = StudentClaim.objects.get(id=instance.id)
        new_status = updated_claim.status
        claim_type = updated_claim.claim_type
        student_user = updated_claim.student.user

        # Human-friendly per-status messages for the student
        status_messages = {
            "approved": (
                f"Great news! Your '{claim_type}' claim has been approved. "
                "Please check the claim details for next steps."
            ),
            "rejected": (
                f"Unfortunately, your '{claim_type}' claim has been rejected. "
                "Please log in to view the reason or contact support for clarification."
            ),
            "under_review": (
                f"Your '{claim_type}' claim is now under review by our team. "
                "We will notify you once a decision has been made."
            ),
            "pending": (
                f"Your '{claim_type}' claim status has been reset to Pending. "
                "Please reach out if you have questions."
            ),
            "resolved": (
                f"Your '{claim_type}' claim has been marked as Resolved. "
                "Thank you for your patience. Contact support if you need further assistance."
            ),
            "closed": (
                f"Your '{claim_type}' claim has been closed. "
                "If you believe this is an error, please submit a new claim or contact support."
            ),
        }

        student_message = status_messages.get(
            new_status,
            f"Your '{claim_type}' claim has been updated to '{new_status}'.",
        )

        notifications_data = [
            {
                "user": student_user,
                "title": f"Claim Update – {claim_type} is now '{new_status.replace('_', ' ').title()}'",
                "message": student_message,
            }
        ]

        # If status actually changed, also alert all other admins
        if old_status != new_status:
            student_full_name = (
                f"{student_user.first_name} {student_user.last_name}".strip()
                or student_user.username
            )
            editor_name = request.user.get_full_name() or request.user.username
            for admin in User.objects.filter(is_superuser=True).exclude(id=request.user.id):
                notifications_data.append(
                    {
                        "user": admin,
                        "title": f"Claim Status Changed – {claim_type}",
                        "message": (
                            f"Claim #{updated_claim.id} for student {student_full_name} "
                            f"was updated from '{old_status}' to '{new_status}' by {editor_name}."
                        ),
                    }
                )

        _bulk_notify(notifications_data)

        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": f"{self._resource_name().title()} updated successfully",
            }
        )

    # ------------------------------------------------------------------ #
    #  DESTROY – notify student claim was deleted; alert other admins
    # ------------------------------------------------------------------ #
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        claim_type = instance.claim_type
        student_user = instance.student.user
        deleter_name = request.user.get_full_name() or request.user.username
        student_full_name = (
            f"{student_user.first_name} {student_user.last_name}".strip()
            or student_user.username
        )

        notifications_data = [
            # Notify the student
            {
                "user": student_user,
                "title": f"Claim Deleted – {claim_type}",
                "message": (
                    f"Your '{claim_type}' claim (ID #{instance.id}) has been deleted by an administrator. "
                    "If you believe this was done in error, please contact support."
                ),
            }
        ]

        # Notify all other admins
        for admin in User.objects.filter(is_superuser=True).exclude(id=request.user.id):
            notifications_data.append(
                {
                    "user": admin,
                    "title": f"Claim Deleted – {claim_type}",
                    "message": (
                        f"Claim #{instance.id} ('{claim_type}') belonging to student {student_full_name} "
                        f"was deleted by {deleter_name}."
                    ),
                }
            )

        _bulk_notify(notifications_data)
        self.perform_destroy(instance)

        return Response(
            {
                "success": True,
                "message": f"{self._resource_name().title()} deleted successfully",
            },
            status=status.HTTP_204_NO_CONTENT,
        )


# --------------------------------------------------------------------------- #
#  StudentClaimViewSet
# --------------------------------------------------------------------------- #
class StudentClaimViewSet(BaseViewSet):
    queryset = StudentClaim.objects.all()
    serializer_class = StudentClaimSerializer
    basename = "student claim"
    filter_backends = [DjangoFilterBackend, SearchFilter]
    search_fields = ["claim_type", "description", "subject"]
    filterset_fields = ["status", "student"]

    def get_permissions(self):
        # if self.action in ["list", "retrieve", "create"]:
        return [permissions.IsAuthenticated()]
        # return [permissions.IsAdminUser()]

    def perform_create(self, serializer):
        try:
            student_instance = Student.objects.get(user=self.request.user)
            serializer.save(student=student_instance)
        except Student.DoesNotExist:
            serializer.save()
        except TypeError:
            serializer.save()

    # ------------------------------------------------------------------ #
    #  ADD RESPONSE – notify student a reply was posted; alert other admins
    # ------------------------------------------------------------------ #
    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def add_response(self, request, pk=None):
        """Add a ClaimResponse to this StudentClaim."""
        claim = self.get_object()

        serializer = ClaimResponseSerializer(
            data={"response_text": request.data.get("message", "")}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(claim=claim, responder=request.user)

        student_user = claim.student.user
        responder_name = request.user.get_full_name() or request.user.username
        student_full_name = (
            f"{student_user.first_name} {student_user.last_name}".strip()
            or student_user.username
        )

        notifications_data = [
            # Notify the student
            {
                "user": student_user,
                "title": f"New Response on Your Claim – {claim.claim_type}",
                "message": (
                    f"{responder_name} has posted a response on your '{claim.claim_type}' claim. "
                   
                ),
            }
        ]

        # Notify all other admins
        for admin in User.objects.filter(is_superuser=True).exclude(id=request.user.id):
            notifications_data.append(
                {
                    "user": admin,
                    "title": f"Response Added to Claim #{claim.id}",
                    "message": (
                        f"{responder_name} responded to the '{claim.claim_type}' claim "
                        f"from student {student_full_name} (Claim #{claim.id})."
                    ),
                }
            )

        _bulk_notify(notifications_data)

        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": "Response added to claim successfully",
            },
            status=status.HTTP_201_CREATED,
        )


# --------------------------------------------------------------------------- #
#  ClaimResponseViewSet
# --------------------------------------------------------------------------- #
class ClaimResponseViewSet(viewsets.ModelViewSet):
    queryset = ClaimResponse.objects.all()
    serializer_class = ClaimResponseSerializer
    basename = "claim response"
    filter_backends = [DjangoFilterBackend, SearchFilter]
    search_fields = ["response_text"]
    filterset_fields = ["claim", "responder"]

    def _resource_name(self):
        try:
            return getattr(self, "basename")
        except Exception:
            return self.get_queryset().model.__name__.lower()

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response({"success": True, "data": serializer.data})

        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": f"{self._resource_name().title()}s fetched successfully",
            }
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": f"{self._resource_name().title()} fetched successfully",
            }
        )

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        user_permissions = user.get_permissions_list()
        if not user.is_staff and "view_claimresponse" not in user_permissions:
            try:
                student = Student.objects.get(user=user)
                queryset = queryset.filter(claim__student=student)
            except Student.DoesNotExist:
                queryset = ClaimResponse.objects.none()

        return queryset

    def get_permissions(self):
        if self.action in ["list", "retrieve", "by_claim"]:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]

    def perform_create(self, serializer):
        serializer.save(responder=self.request.user)

    # ------------------------------------------------------------------ #
    #  CREATE response – notify student; alert other admins
    # ------------------------------------------------------------------ #
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)

        claim_response = ClaimResponse.objects.select_related(
            "claim__student__user"
        ).get(id=serializer.data["id"])
        claim = claim_response.claim
        student_user = claim.student.user
        responder_name = request.user.get_full_name() or request.user.username
        student_full_name = (
            f"{student_user.first_name} {student_user.last_name}".strip()
            or student_user.username
        )

        notifications_data = [
            {
                "user": student_user,
                "title": f"New Response on Your Claim – {claim.claim_type}",
                "message": (
                    f"{responder_name} has posted a response on your '{claim.claim_type}' claim. "
                    "Please log in to read the full response."
                ),
            }
        ]

        for admin in User.objects.filter(is_superuser=True).exclude(id=request.user.id):
            notifications_data.append(
                {
                    "user": admin,
                    "title": f"Response Added to Claim #{claim.id}",
                    "message": (
                        f"{responder_name} responded to the '{claim.claim_type}' claim "
                        f"from student {student_full_name} (Claim #{claim.id})."
                    ),
                }
            )

        _bulk_notify(notifications_data)

        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": f"{self._resource_name().title()} created successfully",
            },
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    # ------------------------------------------------------------------ #
    #  UPDATE response – notify student the reply was edited
    # ------------------------------------------------------------------ #
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        claim = instance.claim
        student_user = claim.student.user
        editor_name = request.user.get_full_name() or request.user.username

        _bulk_notify(
            [
                {
                    "user": student_user,
                    "title": f"Response Updated on Your Claim – {claim.claim_type}",
                    "message": (
                        f"A response on your '{claim.claim_type}' claim (Claim #{claim.id}) "
                        f"has been edited by {editor_name}. Please log in to view the updated response."
                    ),
                }
            ]
        )

        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": f"{self._resource_name().title()} updated successfully",
            }
        )

    # ------------------------------------------------------------------ #
    #  DESTROY response – notify student the reply was removed
    # ------------------------------------------------------------------ #
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        claim = instance.claim
        student_user = claim.student.user
        deleter_name = request.user.get_full_name() or request.user.username

        _bulk_notify(
            [
                {
                    "user": student_user,
                    "title": f"Response Removed from Your Claim – {claim.claim_type}",
                    "message": (
                        f"A response on your '{claim.claim_type}' claim (Claim #{claim.id}) "
                        f"has been removed by {deleter_name}. "
                        "Please contact support if you have questions."
                    ),
                }
            ]
        )

        self.perform_destroy(instance)

        return Response(
            {
                "success": True,
                "message": f"{self._resource_name().title()} deleted successfully",
            },
            status=status.HTTP_204_NO_CONTENT,
        )

    # ------------------------------------------------------------------ #
    #  BY_CLAIM – read-only, no notification needed
    # ------------------------------------------------------------------ #
    @action(detail=False, methods=["get"])
    def by_claim(self, request):
        """
        Get all responses for a specific claim.
        Example: GET /api/claims/responses/by_claim/?claim=1
        """
        claim_id = request.query_params.get("claim")
        if not claim_id:
            return Response(
                {"success": False, "message": "claim parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            claim_id = int(claim_id)
            claim = StudentClaim.objects.get(id=claim_id)

            user = request.user
            if not user.is_staff:
                try:
                    student = Student.objects.get(user=user)
                    if claim.student != student:
                        return Response(
                            {
                                "success": False,
                                "message": "You can only view responses for your own claims",
                            },
                            status=status.HTTP_403_FORBIDDEN,
                        )
                except Student.DoesNotExist:
                    return Response(
                        {"success": False, "message": "Student record not found"},
                        status=status.HTTP_403_FORBIDDEN,
                    )

            responses = self.get_queryset().filter(claim=claim)
            serializer = self.get_serializer(responses, many=True)

            return Response(
                {
                    "success": True,
                    "data": serializer.data,
                    "message": f"Responses for claim #{claim_id} fetched successfully",
                }
            )

        except (ValueError, TypeError):
            return Response(
                {"success": False, "message": "Invalid claim ID format"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except StudentClaim.DoesNotExist:
            return Response(
                {"success": False, "message": f"Claim with id {claim_id} not found"},
                status=status.HTTP_404_NOT_FOUND,
            )