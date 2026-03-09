from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from django.db.models import Count

from .models import CheatingReport, CheatingEvidence
from .permissions import IsInstructor, IsAdminUser, IsReportOwnerOrAdmin
from .serializers import (
    CheatingReportSerializer,
    CheatingReportCreateSerializer,
    CheatingReportAdminUpdateSerializer,
    CheatingReportListSerializer,
    CheatingEvidenceSerializer,
)
from users.models import User
from notifications.models import Notification
from notifications.tasks import send_notification, send_email_task


def _build_and_send_notifications(notifications_data):
    """
    Accepts a list of dicts: {user, title, message}
    Bulk-creates Notification objects then pushes each via send_notification.
    """
    objs = [
        Notification(user=d["user"], title=d["title"], message=d["message"])
        for d in notifications_data
    ]
    created = Notification.objects.bulk_create(objs)
    for notification in created:
        payload = {
            "id": notification.id,
            "title": notification.title,
            "message": notification.message,
            "created_at": notification.created_at.isoformat(),
            "is_read": notification.is_read,
            "read_at": notification.read_at.isoformat() if notification.read_at else None,
        }
        send_notification(payload, notification.user.id)


class InstructorReportListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return CheatingReportCreateSerializer
        return CheatingReportListSerializer

    def get_queryset(self):
        return (
            CheatingReport.objects
            .filter(reported_by=self.request.user)
            .select_related("exam", "student", "reported_by")
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        report = serializer.save()
        out = CheatingReportSerializer(report, context={"request": request})

        instructor_name = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
        student_name = f"{report.student.first_name} {report.student.last_name}".strip() or report.student.username
        exam_name = getattr(report.exam, "title", f"Exam #{report.exam.pk}")
        severity = report.get_severity_display() if hasattr(report, "get_severity_display") else report.severity

        notifications_data = [
            # Notify the accused student
            {
                "user": report.student,
                "title": "Academic Integrity Report Filed Against You",
                "message": (
                    f"A cheating report has been filed against you by {instructor_name} "
                    f"regarding '{exam_name}'. Severity level: {severity}. "
                    "Please contact your instructor or academic office if you have any questions."
                ),
            },
            # Notify the reporting instructor (confirmation)
            {
                "user": request.user,
                "title": "Cheating Report Submitted Successfully",
                "message": (
                    f"Your cheating report for student {student_name} "
                    f"regarding '{exam_name}' (severity: {severity}) has been submitted "
                    "and is now pending admin review."
                ),
            },
        ]

        # Notify all admins
        admin_users = User.objects.filter(is_superuser=True)
        for admin in admin_users:
            notifications_data.append({
                "user": admin,
                "title": f"New Cheating Report — {exam_name}",
                "message": (
                    f"Instructor {instructor_name} has filed a {severity}-severity cheating report "
                    f"against student {student_name} for '{exam_name}'. "
                    f"Details: {report.incident_description}"
                ),
            })

        _build_and_send_notifications(notifications_data)

        return Response(out.data, status=status.HTTP_201_CREATED)


class InstructorReportDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CheatingReportSerializer

    def get_queryset(self):
        return CheatingReport.objects.select_related(
            "exam", "student", "reported_by", "reviewed_by"
        ).prefetch_related("evidence")


class AdminReportListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CheatingReportListSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["status", "severity", "exam", "student", "reported_by"]
    search_fields = [
        "incident_description",
        "student__first_name",
        "student__last_name",
        "student__username",
    ]
    ordering_fields = ["created_at", "severity", "status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return CheatingReport.objects.select_related("exam", "student", "reported_by").all()


class AdminReportDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    queryset = CheatingReport.objects.select_related(
        "exam", "student", "reported_by", "reviewed_by"
    ).prefetch_related("evidence")

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return CheatingReportAdminUpdateSerializer
        return CheatingReportSerializer

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        old_status = instance.status

        response = super().update(request, *args, **kwargs)

        # Reload fresh instance after save
        instance.refresh_from_db()
        new_status = instance.status

        admin_name = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
        student_name = f"{instance.student.first_name} {instance.student.last_name}".strip() or instance.student.username
        instructor_name = f"{instance.reported_by.first_name} {instance.reported_by.last_name}".strip() or instance.reported_by.username
        exam_name = getattr(instance.exam, "title", f"Exam #{instance.exam.pk}")
        severity = instance.get_severity_display() if hasattr(instance, "get_severity_display") else instance.severity

        STATUS_LABELS = {
            "pending":    "Pending Review",
            "reviewing":  "Under Review",
            "resolved":   "Resolved",
            "dismissed":  "Dismissed",
        }
        new_status_label = STATUS_LABELS.get(new_status, new_status.title())

        notifications_data = []

        if old_status != new_status:
            # Tell the student their case status changed
            notifications_data.append({
                "user": instance.student,
                "title": f"Your Academic Integrity Case Is Now '{new_status_label}'",
                "message": (
                    f"The cheating report filed against you for '{exam_name}' has been updated "
                    f"to status '{new_status_label}' by the academic office. "
                    "Please check your student portal for further details or required actions."
                ),
            })

            # Tell the reporting instructor their report was actioned
            notifications_data.append({
                "user": instance.reported_by,
                "title": f"Your Cheating Report Status Updated to '{new_status_label}'",
                "message": (
                    f"The cheating report you filed against {student_name} for '{exam_name}' "
                    f"has been reviewed by {admin_name} and its status is now '{new_status_label}'."
                ),
            })

        # Always notify other admins when a report is edited (excluding the editor)
        other_admins = User.objects.filter(is_superuser=True).exclude(pk=request.user.pk)
        for admin in other_admins:
            notifications_data.append({
                "user": admin,
                "title": f"Cheating Report Updated — {exam_name}",
                "message": (
                    f"Admin {admin_name} has updated the cheating report for student {student_name} "
                    f"on '{exam_name}' (severity: {severity}). "
                    f"Status: {old_status.title()} → {new_status_label}."
                ),
            })

        if notifications_data:
            _build_and_send_notifications(notifications_data)

        return response


class EvidenceCreateView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CheatingEvidenceSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_report(self):
        try:
            report = CheatingReport.objects.get(pk=self.kwargs["report_pk"])
        except CheatingReport.DoesNotExist:
            raise NotFound("Report not found.")
        if not self.request.user.is_superuser and report.reported_by != self.request.user:
            raise PermissionDenied("You can only add evidence to your own reports.")
        return report

    def perform_create(self, serializer):
        report = self.get_report()
        serializer.save(report=report, uploaded_by=self.request.user)

        uploader_name = f"{self.request.user.first_name} {self.request.user.last_name}".strip() or self.request.user.username
        student_name = f"{report.student.first_name} {report.student.last_name}".strip() or report.student.username
        exam_name = getattr(report.exam, "title", f"Exam #{report.exam.pk}")

        notifications_data = []

        # Notify all admins that new evidence was attached
        admin_users = User.objects.filter(is_superuser=True)
        for admin in admin_users:
            notifications_data.append({
                "user": admin,
                "title": f"New Evidence Added — {exam_name}",
                "message": (
                    f"{uploader_name} has uploaded new evidence to the cheating report "
                    f"for student {student_name} on '{exam_name}'. "
                    "Please review the updated report."
                ),
            })

        # If evidence added by admin, also notify the reporting instructor
        if self.request.user.is_superuser:
            notifications_data.append({
                "user": report.reported_by,
                "title": f"New Evidence Added to Your Report — {exam_name}",
                "message": (
                    f"An admin ({uploader_name}) has attached additional evidence to your "
                    f"cheating report for student {student_name} on '{exam_name}'."
                ),
            })

        if notifications_data:
            _build_and_send_notifications(notifications_data)


class EvidenceDeleteView(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CheatingEvidence.objects.filter(report_id=self.kwargs["report_pk"])

    def get_object(self):
        obj = super().get_object()
        if not self.request.user.is_superuser and obj.uploaded_by != self.request.user:
            raise PermissionDenied("You can only delete evidence you uploaded.")
        return obj

    def perform_destroy(self, instance):
        report = instance.report
        deleter_name = f"{self.request.user.first_name} {self.request.user.last_name}".strip() or self.request.user.username
        student_name = f"{report.student.first_name} {report.student.last_name}".strip() or report.student.username
        exam_name = getattr(report.exam, "title", f"Exam #{report.exam.pk}")

        instance.delete()

        notifications_data = []

        # Notify admins about evidence removal
        admin_users = User.objects.filter(is_superuser=True).exclude(pk=self.request.user.pk)
        for admin in admin_users:
            notifications_data.append({
                "user": admin,
                "title": f"Evidence Removed — {exam_name}",
                "message": (
                    f"{deleter_name} has deleted a piece of evidence from the cheating report "
                    f"for student {student_name} on '{exam_name}'. Please review if necessary."
                ),
            })

        # Notify the instructor if an admin deleted their evidence
        if self.request.user.is_superuser and report.reported_by != self.request.user:
            notifications_data.append({
                "user": report.reported_by,
                "title": f"Evidence Removed From Your Report — {exam_name}",
                "message": (
                    f"Admin {deleter_name} has removed a piece of evidence from your cheating "
                    f"report for student {student_name} on '{exam_name}'."
                ),
            })

        if notifications_data:
            _build_and_send_notifications(notifications_data)


class ReportStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        by_status   = CheatingReport.objects.values("status").annotate(count=Count("id"))
        by_severity = CheatingReport.objects.values("severity").annotate(count=Count("id"))
        return Response({
            "total":       CheatingReport.objects.count(),
            "by_status":   {i["status"]: i["count"] for i in by_status},
            "by_severity": {i["severity"]: i["count"] for i in by_severity},
        })