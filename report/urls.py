from django.urls import path
from .views import TimetablePDFView
from .attendance_views import (
    AttendanceStatsView,
    ExamAttendanceListView,
    CheatingReportActionView,
    AttendancePDFView,
)

urlpatterns = [
    path('', TimetablePDFView.as_view(), name='timetable-pdf'),
    path("attendance/stats/",  AttendanceStatsView.as_view(),    name="attendance-stats"),
    path("attendance/",        ExamAttendanceListView.as_view(), name="exam-attendance"),
    path("attendance/pdf/",    AttendancePDFView.as_view(),      name="attendance-pdf"),
    path("cheating/<int:report_id>/action/", CheatingReportActionView.as_view(), name="cheating-action"),

]