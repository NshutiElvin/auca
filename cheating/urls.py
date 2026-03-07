from django.urls import path
from .views import (
    InstructorReportListCreateView,
    InstructorReportDetailView,
    AdminReportListView,
    AdminReportDetailView,
    EvidenceCreateView,
    EvidenceDeleteView,
    ReportStatsView,
)

urlpatterns = [
    # Instructor
    path("mine/",          InstructorReportListCreateView.as_view(), name="instructor-report-list-create"),
    path("mine/<int:pk>/", InstructorReportDetailView.as_view(),     name="instructor-report-detail"),

    # Evidence
    path("<int:report_pk>/evidence/",          EvidenceCreateView.as_view(), name="evidence-create"),
    path("<int:report_pk>/evidence/<int:pk>/", EvidenceDeleteView.as_view(), name="evidence-delete"),

    # Admin
    path("admin/",              AdminReportListView.as_view(),   name="admin-report-list"),
    path("admin/stats/",        ReportStatsView.as_view(),       name="admin-report-stats"),
    path("admin/<int:pk>/",     AdminReportDetailView.as_view(), name="admin-report-detail"),
]