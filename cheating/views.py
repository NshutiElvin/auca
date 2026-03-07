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


class InstructorReportListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsInstructor]

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
        return Response(out.data, status=status.HTTP_201_CREATED)


class InstructorReportDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated, IsInstructor, IsReportOwnerOrAdmin]
    serializer_class = CheatingReportSerializer

    def get_queryset(self):
        return CheatingReport.objects.select_related(
            "exam", "student", "reported_by", "reviewed_by"
        ).prefetch_related("evidence")


class AdminReportListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsAdminUser]
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
    permission_classes = [IsAuthenticated, IsAdminUser]
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


class EvidenceCreateView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated, IsInstructor]
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


class EvidenceDeleteView(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CheatingEvidence.objects.filter(report_id=self.kwargs["report_pk"])

    def get_object(self):
        obj = super().get_object()
        if not self.request.user.is_superuser and obj.uploaded_by != self.request.user:
            raise PermissionDenied("You can only delete evidence you uploaded.")
        return obj


class ReportStatsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        by_status   = CheatingReport.objects.values("status").annotate(count=Count("id"))
        by_severity = CheatingReport.objects.values("severity").annotate(count=Count("id"))
        return Response({
            "total":       CheatingReport.objects.count(),
            "by_status":   {i["status"]: i["count"] for i in by_status},
            "by_severity": {i["severity"]: i["count"] for i in by_severity},
        })