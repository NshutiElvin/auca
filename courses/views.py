from rest_framework import viewsets, status, permissions
from rest_framework.response import Response

from semesters.models import Semester
from .models import Course
from .serializers import (
    CourseSerializer,
)
from .permissions import IsAdminOrInstructor, IsStudent
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from enrollments.models import Enrollment
from django.db.models import Count
from rest_framework.response import Response
from .models import CourseGroup
from config.utils import JsonConfigManager
from .serializers import CourseGroupSerializer
from users.models import User



class BaseViewSet(viewsets.ModelViewSet):
    """
    Base ViewSet to format responses consistently
    """

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        courses = serializer.data

        course_ids = [course["id"] for course in courses]

        enrollments_count = (
            Enrollment.objects.filter(course_id__in=course_ids)
            .values("course_id")
            .annotate(students_enrolled=Count("id"))
        )
        enrollments_map = {
            e["course_id"]: e["students_enrolled"] for e in enrollments_count
        }

        for course in courses:
            course["students_enrolled"] = enrollments_map.get(course["id"], 0)

        return Response(
            {
                "success": True,
                "data": courses,
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

    @action(detail=False, methods=["post"], url_path="timetable-courses")
    def timetable_tables(self, request, *args, **kwargs):
        try:
            client_conf = request.data.get("configurations")
            semester = Semester.objects.get(is_active=True).id
            location = client_conf.get("location")
            print(semester, location)
            courses = Course.objects.filter(
                semester__id=int(semester), department__location_id=int(location)
            )
            coursesSerializer = CourseSerializer(courses, many=True)
            return Response(
                {
                    "success": True,
                    "data": coursesSerializer.data,
                    "message": f"timetable courses retrieved successfully",
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to get the timetable courses"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=False,
        methods=["PUT"],
        url_path="update-course-group-times/(?P<course_id>[^/.]+)/(?P<group_id>[^/.]+)",
    )
    def update_course_group_times(self, request, course_id, group_id, *args, **kwargs):
        try:
            dayTime = request.data.get("dayTime")
            selected_instructor= request.data.get("instructor")
            wanted_instructor= None
            start_time = None
            end_time = None
            if selected_instructor:
                wanted_instructor=User.objects.get(id=int(selected_instructor))
            config_manager = JsonConfigManager()
            config = config_manager.read_config()
            time_config = config.get("time_constraints", {})
            time_slots = time_config.get("time_slots", [])
            for slot in time_slots:
                if slot.get("name").lower() == dayTime.lower():
                    start_time = slot.get("start_time")
                    end_time = slot.get("end_time")
                    break
            course_group = CourseGroup.objects.get(id=group_id, course__id=course_id)
            course_group.start_time = start_time
            course_group.end_time = end_time
            if wanted_instructor:
                course_group.instructor = wanted_instructor
            course_group.save()
            return Response(
                {"success": True, "message": "Course group times updated successfully"},
                status=status.HTTP_200_OK,
            )
        except CourseGroup.DoesNotExist:
            return Response(
                {"success": False, "message": "Course group not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to update course group times"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # action to get the course groups for a specific course that will be used by the timetable algorithm to get the course groups for a specific course
    @action(detail=True, methods=["get"], url_path="course-groups")
    def course_groups(self, request, pk=None, *args, **kwargs):
        try:
            course_groups = CourseGroup.objects.filter(course__id=pk)
            course_groups_serializer = CourseGroupSerializer(course_groups, many=True)
            return Response(
                {
                    "success": True,
                    "data": course_groups_serializer.data,
                    "message": "Course groups retrieved successfully",
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to retrieve course groups"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class CourseViewSet(BaseViewSet):
    queryset = Course.objects.all()
    serializer_class = CourseSerializer
    basename = "course"
    filter_backends = [DjangoFilterBackend, SearchFilter]
    search_fields = ["code", "title"]
    filterset_fields = ["semester", "department"]
    ordering_fields = ["code", "title", "semester", "created_at"]
    ordering = ["code"]

    def get_permissions(self):
        if self.action in ["list", "retrieve", "enrollments"]:
            return [permissions.IsAuthenticated()]
        return [IsAdminOrInstructor()]

    @action(
        detail=True, methods=["get"], permission_classes=[permissions.IsAuthenticated]
    )
    def enrollments(self, request, pk=None):
        course = self.get_object()
        enrollments = Enrollment.objects.filter(course=course)
        serializer = EnrollmentSerializer(enrollments, many=True)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": f"Enrollments for course {course.code} fetched successfully",
            }
        )
