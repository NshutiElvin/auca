from collections import defaultdict
from rest_framework import viewsets, status, permissions
from rest_framework.response import Response

from exams.models import Exam, StudentExam
from exams.serializers import ExamSerializer
from .models import CourseSchedule, MasterTimetable, MasterTimetableExam
from .serializers import (
    CourseScheduleSerializer,
    MasterTimetableSerializer,
)
from .permissions import IsAdminOrInstructor
from rest_framework.decorators import action
from .utils import get_exam_slots
import json
import datetime
from django.utils.dateparse import parse_date
from pytz import timezone as pytz_timezone
from django.conf import settings
from django.utils import timezone
from django.db.models import Count


class CourseScheduleViewSet(viewsets.ModelViewSet):
    queryset = CourseSchedule.objects.all()
    serializer_class = CourseScheduleSerializer
    basename = "schedule"

    """
    Base ViewSet to format responses consistently
    """

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": f"{self.basename.title()}s fetched successfully",
            }
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": f"{self.basename.title()} fetched successfully",
            }
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": f"{self.basename.title()} created successfully",
            },
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": f"{self.basename.title()} updated successfully",
            }
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(
            {
                "success": True,
                "message": f"{self.basename.title()} deleted successfully",
            },
            status=status.HTTP_204_NO_CONTENT,
        )

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.IsAuthenticated()]
        return [IsAdminOrInstructor()]

    @action(detail=False, methods=["post"], url_path="generate_slots")
    def generate_slots(self, request, *args, **kwargs):
        try:
            start_date_str = request.data.get("start_date")
            end_date_str = request.data.get("end_date")

            if start_date_str and "T" in start_date_str:
                start_date_str = start_date_str.split("T")[0]
            if end_date_str and "T" in end_date_str:
                end_date_str = end_date_str.split("T")[0]

            date = request.data.get("date")
            if date and "T" in date:
                date = date.split("T")[0]

            start_date = parse_date(start_date_str) if start_date_str else None
            end_date = parse_date(end_date_str) if end_date_str else None

            slots = get_exam_slots(start_date, end_date)
            slots_by_date = defaultdict(list)

            for slot_idx, (date, label, start, end) in enumerate(slots):
                slots_by_date[date.isoformat()].append((slot_idx, label, start, end))
            return Response(
                {
                    "success": True,
                    "data": slots_by_date,
                    "message": "Exam slots generated successfully.",
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {
                    "success": False,
                    "data": str(e),
                    "message": "Failed to generate exams slots. Please Try again.",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], url_path="dashboard")
    def dashboard(self, request, *args, **kwargs):
        try:
            location= request.GET.get("location")
            tz = pytz_timezone(settings.TIME_ZONE)
            now = timezone.now().astimezone(tz)
            today = now.date()

            recent_timetable = MasterTimetable.objects.order_by("-created_at").first()
            if location:
                recent_timetable=MasterTimetable.objects.filter(location_id=location).order_by("-created_at").first()
                

            if not recent_timetable:
                return Response(
                    {
                        "success": False,
                        "message": "No timetable found",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            recent_exams = Exam.objects.filter(
                mastertimetableexam__master_timetable=recent_timetable
            )

            today_students = StudentExam.objects.filter(
                exam__date=today,
                exam__status__in=["READY", "ONGOING"],
            ).count()

            total_exams = recent_exams.count()
            ongoing_exams = recent_exams.filter(status="ONGOING").count()
            completed_exams = recent_exams.filter(status="COMPLETED").count()
            scheduled_exams = recent_exams.filter(status="SCHEDULED").count()
            cancelled_exams = recent_exams.filter(status="CANCELLED").count()

            ongoing_percentage = (
                round((ongoing_exams / total_exams) * 100, 2) if total_exams else 0
            )
            completed_percentage = (
                round((completed_exams / total_exams) * 100, 2) if total_exams else 0
            )
            scheduled_percentage = (
                round((scheduled_exams / total_exams) * 100, 2) if total_exams else 0
            )
            cancelled_percentage = (
                round((cancelled_exams / total_exams) * 100, 2) if total_exams else 0
            )

            start_date = timezone.now().date() - datetime.timedelta(days=7)
            days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Sunday"]
            weekly_exams = []
            for day in days:
                day_exams = (
                    recent_exams.filter(
                        date__gte=start_date, date__week_day=days.index(day) + 1
                    )
                    .annotate(student_count=Count("studentexam"))
                    .order_by("-student_count")
                )

                weekly_exams.append(
                    {
                        "day": day,
                        "exams": [
                            {
                                "id": exam.id,
                                "name": exam.group.course.title
                                + " "
                                + exam.group.group_name,
                                "student_count": exam.student_count,
                                "date": exam.date,
                            }
                            for exam in day_exams
                        ],
                    }
                )

            exams_most_students = recent_exams.annotate(
                student_count=Count("studentexam")
            ).order_by("-student_count")[:5]
            today_exams = (
                recent_exams.filter(date=today)
                .select_related("group")
                .order_by("start_time")
            ).count()
            recent_completed_exams = (
                recent_exams.filter(date=today, status="COMPLETED")
                .select_related("group")
                .order_by("start_time")
            ).count()
            expected_exams = (
                recent_exams.filter(date=today, status="SCHEDULED")
                .select_related("group")
                .order_by("start_time")
            ).count()
            upcoming_exams = (
                recent_exams.filter(date=today, status="READY")
                .select_related("group")
                .order_by("start_time")
            ).count()
            recent_timetables= MasterTimetable.objects.order_by("-created_at").all()[:5]
            if location:
                recent_timetables=MasterTimetable.objects.filter(location_id=location).order_by("-created_at").all()[:5]
            serializer= MasterTimetableSerializer(recent_timetables, many=True)

            return Response(
                {
                    "success": True,
                    "data": {
                        "today_students": today_students,
                        'today_exams':today_exams,
                        "total_exams": total_exams,
                        "ongoing_exams": ongoing_exams,
                        "completed_exams": completed_exams,
                        "ongoing_percentage": ongoing_percentage,
                        "completed_percentage": completed_percentage,
                        "scheduled_percentage": scheduled_percentage,
                        "cancelled_percentage": cancelled_percentage,
                        "recent_completed_exams":recent_completed_exams,
                        "recent_expected_exams":expected_exams,
                        "upcoming_exams": upcoming_exams,
                        "last_updated": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "exams_with_most_students": [
                            {
                                "id": exam.id,
                                "name": exam.group.course.title
                                + " "
                                + exam.group.group_name,
                                "student_count": exam.student_count,
                            }
                            for exam in exams_most_students
                        ],
                        "weekly_exams_by_day": weekly_exams,
                        "recent_exams": serializer.data
                    },
                    "message": "Dashboard data retrieved successfully",
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            print(f"Dashboard error: {str(e)}")
            return Response(
                {
                    "success": False,
                    "message": "Failed to load dashboard data. Please try again.",
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
    def get_recent_timetable(self, location=None):
            """Helper method to get recent timetable"""
            queryset = MasterTimetable.objects.all()
            if location:
                queryset = queryset.filter(location_id=location)
            return queryset.order_by("-created_at").first()
    
    def get_recent_exams(self, recent_timetable):
        """Helper method to get exams from recent timetable"""
        return Exam.objects.filter(
            mastertimetableexam__master_timetable=recent_timetable
        ).select_related('group__course', 'group')

    # Main dashboard summary (your existing code)
    @action(detail=False, methods=["get"], url_path="summary")
    def dashboard_summary(self, request):
        # Your existing dashboard code here
        pass

    # 1. Today's Exams
    @action(detail=False, methods=["get"], url_path="today-exams")
    def today_exams(self, request):
        try:
            location = request.GET.get("location")
            tz = pytz_timezone(settings.TIME_ZONE)
            now = timezone.now().astimezone(tz)
            today = now.date()

            recent_timetable = self.get_recent_timetable(location)
            if not recent_timetable:
                return Response(
                    {"success": False, "message": "No timetable found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            today_exams = self.get_recent_exams(recent_timetable).filter(
                date=today
            ).order_by('start_time')

            # Add pagination if needed
            page = self.paginate_queryset(today_exams)
            if page is not None:
                serializer = ExamSerializer(page, many=True)
                return self.get_paginated_response(serializer.data)

            serializer = ExamSerializer(today_exams, many=True)
            
            return Response({
                "success": True,
                "count": today_exams.count(),
                "data": serializer.data,
                "date": today,
                "message": "Today's exams retrieved successfully"
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "success": False,
                "message": "Failed to load today's exams",
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # 2. Ongoing Exams
    @action(detail=False, methods=["get"], url_path="ongoing-exams")
    def ongoing_exams(self, request):
        try:
            location = request.GET.get("location")
            recent_timetable = self.get_recent_timetable(location)
            
            if not recent_timetable:
                return Response(
                    {"success": False, "message": "No timetable found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            ongoing_exams = self.get_recent_exams(recent_timetable).filter(
                status="ONGOING"
            ).order_by('start_time')

            serializer = ExamSerializer(ongoing_exams, many=True)
            
            return Response({
                "success": True,
                "count": ongoing_exams.count(),
                "data": serializer.data,
                "message": "Ongoing exams retrieved successfully"
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "success": False,
                "message": "Failed to load ongoing exams",
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # 3. Completed Exams
    @action(detail=False, methods=["get"], url_path="completed-exams")
    def completed_exams(self, request):
        try:
            location = request.GET.get("location")
            date_filter = request.GET.get("date")  # Optional date filter
            
            recent_timetable = self.get_recent_timetable(location)
            if not recent_timetable:
                return Response(
                    {"success": False, "message": "No timetable found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            completed_exams = self.get_recent_exams(recent_timetable).filter(
                status="COMPLETED"
            )
            
            if date_filter:
                completed_exams = completed_exams.filter(date=date_filter)

            completed_exams = completed_exams.order_by('-date', '-end_time')

            serializer = ExamSerializer(completed_exams, many=True)
            
            return Response({
                "success": True,
                "count": completed_exams.count(),
                "data": serializer.data,
                "message": "Completed exams retrieved successfully"
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "success": False,
                "message": "Failed to load completed exams",
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # 4. Scheduled Exams
    @action(detail=False, methods=["get"], url_path="scheduled-exams")
    def scheduled_exams(self, request):
        try:
            location = request.GET.get("location")
            recent_timetable = self.get_recent_timetable(location)
            
            if not recent_timetable:
                return Response(
                    {"success": False, "message": "No timetable found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            scheduled_exams = self.get_recent_exams(recent_timetable).filter(
                status="SCHEDULED"
            ).order_by('date', 'start_time')

            serializer = ExamSerializer(scheduled_exams, many=True)
            
            return Response({
                "success": True,
                "count": scheduled_exams.count(),
                "data": serializer.data,
                "message": "Scheduled exams retrieved successfully"
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "success": False,
                "message": "Failed to load scheduled exams",
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # 5. Exams with Most Students
    @action(detail=False, methods=["get"], url_path="popular-exams")
    def popular_exams(self, request):
        try:
            location = request.GET.get("location")
            limit = int(request.GET.get('limit', 10))  # Default to top 10
            
            recent_timetable = self.get_recent_timetable(location)
            if not recent_timetable:
                return Response(
                    {"success": False, "message": "No timetable found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            popular_exams = self.get_recent_exams(recent_timetable).annotate(
                student_count=Count('studentexam')
            ).order_by('-student_count')[:limit]

            # Custom serializer to include student_count
            exam_data = []
            for exam in popular_exams:
                exam_data.append({
                    'id': exam.id,
                    'name': f"{exam.group.course.title} {exam.group.group_name}",
                    'date': exam.date,
                    'start_time': exam.start_time,
                    'end_time': exam.end_time,
                    'status': exam.status,
                    'student_count': exam.student_count,
                    'location': exam.group.location.name if exam.group.location else None
                })
            
            return Response({
                "success": True,
                "count": len(popular_exams),
                "data": exam_data,
                "message": "Popular exams retrieved successfully"
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "success": False,
                "message": "Failed to load popular exams",
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # 6. Weekly Exams Breakdown
    @action(detail=False, methods=["get"], url_path="weekly-exams")
    def weekly_exams(self, request):
        try:
            location = request.GET.get("location")
            recent_timetable = self.get_recent_timetable(location)
            
            if not recent_timetable:
                return Response(
                    {"success": False, "message": "No timetable found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            start_date = timezone.now().date() - datetime.timedelta(days=7)
            days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            
            weekly_data = []
            for i, day in enumerate(days, 1):
                day_exams = self.get_recent_exams(recent_timetable).filter(
                    date__gte=start_date,
                    date__week_day=i
                ).annotate(student_count=Count('studentexam')).order_by('-student_count')
                
                weekly_data.append({
                    "day": day,
                    "total_exams": day_exams.count(),
                    "total_students": sum(exam.student_count for exam in day_exams),
                    "exams": [
                        {
                            "id": exam.id,
                            "name": f"{exam.group.course.title} {exam.group.group_name}",
                            "student_count": exam.student_count,
                            "date": exam.date,
                            "status": exam.status
                        }
                        for exam in day_exams
                    ]
                })
            
            return Response({
                "success": True,
                "data": weekly_data,
                "period": f"{start_date} to {timezone.now().date()}",
                "message": "Weekly exams data retrieved successfully"
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "success": False,
                "message": "Failed to load weekly exams data",
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # 7. Today's Students Count by Exam
    @action(detail=False, methods=["get"], url_path="today-students")
    def today_students(self, request):

        print("Fetching today's students data")
        try:
            location = request.GET.get("location")
            tz = pytz_timezone(settings.TIME_ZONE)
            now = timezone.now().astimezone(tz)
            today = now.date()

            recent_timetable = self.get_recent_timetable(location)
            if not recent_timetable:
                return Response(
                    {"success": False, "message": "No timetable found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Get today's exams with student counts
            today_exams = self.get_recent_exams(recent_timetable).filter(
                date=today
            ).annotate(
                student_count=Count('studentexam')
            ).order_by('start_time')

            exam_data = []
            total_students = 0
            
            for exam in today_exams:
                exam_data.append({
                    'exam_id': exam.id,
                    'exam_name': f"{exam.group.course.title} {exam.group.group_name}",
                    'start_time': exam.start_time,
                    'end_time': exam.end_time,
                    'status': exam.status,
                    'student_count': exam.student_count,
                    'location': exam.group.course.department.location.name if exam.group.course.department.location.name else None
                })
                total_students += exam.student_count

            return Response({
                "success": True,
                "date": today,
                "total_students": total_students,
                "total_exams": today_exams.count(),
                "data": exam_data,
                "message": "Today's students data retrieved successfully"
            }, status=status.HTTP_200_OK)

        except Exception as e:
            print(f"Error fetching today's students data: {str(e)}")
            return Response({
                "success": False,
                "message": "Failed to load today's students data",
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    @action(detail=False, methods=["get"], url_path="timetables")
    def timetables(self, request, *args, **kwargs):
        try:
            recent_timetables= MasterTimetable.objects.order_by("-created_at").all()
            serializer= MasterTimetableSerializer(recent_timetables, many=True)
            return Response(
                {
                    "success": True,
                    "data": serializer.data,
                    "message": "Timetable retrieved successfully.",
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {
                    "success": False,
                    "data": str(e),
                    "message": "Failed to retrieves. Please Try again.",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )