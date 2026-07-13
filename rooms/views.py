from django.conf import settings
from django.shortcuts import render

from rest_framework import viewsets, status, permissions
from rest_framework.response import Response

from config.utils import JsonConfigManager
from courses.serializers import CourseSerializer, SemesterSerializer
from enrollments.models import Enrollment
from exams.serializers import StudentExamSerializer
from schedules.models import MasterTimetable

from semesters.models import Semester
from .models import Location, Room, RoomAllocationSwitch, RoomOutOfService
from .permissions import IsAdminOrInstructor as RoomsIsAdminOrInstructor
from rest_framework.decorators import action, permission_classes
from .serializers import (
    LocationSerializer,
    RoomSerializer,
    RoomAllocationSwitchSerializer,
    RoomOutOfServiceSerializer,
)
from django.contrib.auth import get_user_model
from exams.models import Exam, StudentExam
from notifications.utils import notify_students_room_changed
from django.db.models import Count
from collections import defaultdict
from django.db import transaction
from django.utils import timezone
from django.db.models import Sum
from django.utils.dateparse import parse_date, parse_time
from pytz import timezone as pytz_timezone
from datetime import time, timedelta
import logging

User = get_user_model()
logger = logging.getLogger(__name__)


# Create your views here.
class RoomViewSet(viewsets.ModelViewSet):
    queryset = Room.objects.all()
    serializer_class = RoomSerializer

    def get_permissions(self):
        if self.action in [
            "verify_room",
            "verify_room_qr",
            "instructor_room_qr",
            "verify_room_student",
            "verify",
        ]:
            return [permissions.AllowAny()]  # No permissions required
        elif self.action in ["list", "retrieve", "get_configurations", "get_locations"]:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
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
                "message": "Fetched successfully",
            }
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": "Created successfully",
            },
            status=status.HTTP_201_CREATED,
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
                "message": "Updated successfully",
            }
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(
            {"success": True, "message": "Deleted successfully"},
            status=status.HTTP_204_NO_CONTENT,
        )

    @action(detail=False, methods=["POST"], url_path="students")
    def students(self, request):
        try:

            with transaction.atomic():
                course_group = request.data.get("courseGroup")
                if not course_group:
                    return Response(
                        {
                            "success": False,
                            "message": "Room and Course Group are required",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                # courseIds (plural) covers the occupancies view merging
                # several groups of the same course/room/slot into one card —
                # falls back to the single courseId any other caller sends.
                exam_ids = course_group.get("courseIds") or [course_group.get("courseId")]
                exams = Exam.objects.filter(id__in=exam_ids)

                existingRoom = Room.objects.filter(
                    name=course_group["roomName"]
                ).first()
                if not exams.exists() or not existingRoom:
                    return Response(
                        {
                            "success": False,
                            "message": "Invalid Room, existing romm and Course Group",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                student_exams = StudentExam.objects.filter(exam__in=exams, room=existingRoom)
                if not student_exams.exists():
                    return Response(
                        {
                            "success": False,
                            "message": "No student exams found for the specified exam and room",
                        },
                        status=status.HTTP_404_NOT_FOUND,
                    )
                students_exams_serialiser = StudentExamSerializer(
                    student_exams, many=True
                )
                students_exams_data = students_exams_serialiser.data
                return Response(
                    {
                        "success": True,
                        "students": students_exams_data,
                        "message": "Students retrieved  successfully",
                    },
                    status=status.HTTP_200_OK,
                )
        except Exception as e:
            return Response(
                {"success": False, "message": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=["POST"], url_path="verify_change_students")
    def verify_change_students(self, request):
        try:
            with transaction.atomic():
                room_data = request.data.get("room")
                students_exams = request.data.get("students")

                # ✅ Validate input data
                if not room_data or not students_exams:
                    return Response(
                        {
                            "success": False,
                            "error_code": "MISSING_FIELDS",
                            "message": "Both 'room' and 'students' fields are required to proceed.",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                room = Room.objects.filter(name=room_data.get("roomName")).first()
                exam_ids = [exam.get("id") for exam in students_exams if "id" in exam]

                if not room:
                    return Response(
                        {
                            "success": False,
                            "error_code": "INVALID_ROOM",
                            "message": f"Room '{room_data.get('roomName')}' does not exist. Please select a valid room.",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                student_exams = StudentExam.objects.filter(id__in=exam_ids)

                if not student_exams.exists():
                    return Response(
                        {
                            "success": False,
                            "error_code": "NO_EXAMS_FOUND",
                            "message": "No matching student exams were found for the provided IDs.",
                        },
                        status=status.HTTP_404_NOT_FOUND,
                    )

                # ✅ Check room occupancy for the same date and time
                exam_date = student_exams[0].exam.date
                exam_start_time = student_exams[0].exam.start_time
                current_room_occupancy = StudentExam.objects.filter(
                    room=room, exam__date=exam_date, exam__start_time=exam_start_time
                ).count()

                total_required_capacity = student_exams.count() + current_room_occupancy

                if room.capacity < total_required_capacity:
                    return Response(
                        {
                            "success": False,
                            "error_code": "ROOM_CAPACITY_EXCEEDED",
                            "message": (
                                f"Room '{room.name}' cannot accommodate this student(s). "
                                f"Capacity ({room.capacity}) is insufficient for "
                                f"{total_required_capacity} students (including {current_room_occupancy} already assigned)."
                            ),
                        },
                        status=status.HTTP_412_PRECONDITION_FAILED,
                    )

                return Response(
                    {
                        "success": True,
                        "message": f"Room '{room.name}' is available and can accommodate the selected course group.",
                    },
                    status=status.HTTP_200_OK,
                )

        except Exception as e:
            return Response(
                {
                    "success": False,
                    "error_code": "INTERNAL_ERROR",
                    "message": f"An unexpected error occurred while verifying room occupancy: {str(e)}",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["PATCH"], url_path="change_students")
    def change_students(self, request):
        try:

            with transaction.atomic():
                room = request.data.get("room")
                students_exams = request.data.get("students")
                if not room or not students_exams:
                    return Response(
                        {
                            "success": False,
                            "message": "Room and Course Group are required",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                room = Room.objects.filter(name=room["roomName"]).first()
                exams = [exam["id"] for exam in students_exams]

                if not room:
                    return Response(
                        {
                            "success": False,
                            "message": "Invalid Room, existing romm and Course Group",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                student_exams = StudentExam.objects.filter(id__in=exams).select_related(
                    "student__user", "exam__group__course", "room"
                )

                if not student_exams.exists():
                    return Response(
                        {
                            "success": False,
                            "message": "No student exams found for the specified exam and room",
                        },
                        status=status.HTTP_404_NOT_FOUND,
                    )
                # Unlike change_room (always "was in existingRoom"), this
                # endpoint takes an arbitrary list of StudentExam ids — some
                # could already be unseated (room was null), so only notify
                # where there's a genuine prior room being changed away from.
                room_changes = []
                for student_exam in student_exams:
                    old_room = student_exam.room
                    if old_room and old_room.id != room.id:
                        room_changes.append((student_exam, old_room, room))
                    student_exam.room = room
                    student_exam.save()
                if room_changes:
                    notify_students_room_changed(room_changes)
                return Response(
                    {"success": True, "message": "Exam room changed successfully"},
                    status=status.HTTP_201_CREATED,
                )
        except Exception as e:
            logger.error(f"Error while changing room occupancy: {e}", exc_info=True)
            return Response(
                {
                    "success": False,
                    "message": "An error occurred while changing room occupancy",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=["POST"], url_path="verify_room_change")
    def verify_room_change(self, request):
        try:
            with transaction.atomic():
                room_data = request.data.get("room")
                course_group = request.data.get("courseGroup")

                # ✅ Validate required fields
                if not room_data or not course_group:
                    return Response(
                        {
                            "success": False,
                            "error_code": "MISSING_FIELDS",
                            "message": "Both 'room' and 'courseGroup' fields are required.",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # ✅ Fetch room and course details
                # courseIds (plural) covers the occupancies view merging
                # several groups of the same course/room/slot into one card —
                # falls back to the single courseId any other caller sends.
                exam_ids = course_group.get("courseIds") or [course_group.get("courseId")]
                exams = Exam.objects.filter(id__in=exam_ids)
                exam = exams.first()
                room = Room.objects.filter(name=room_data.get("roomName")).first()
                existing_room = Room.objects.filter(
                    name=course_group.get("roomName")
                ).first()

                if not exam or not room or not existing_room:
                    return Response(
                        {
                            "success": False,
                            "error_code": "INVALID_DATA",
                            "message": (
                                f"Invalid data provided. "
                                f"Exam exists: {bool(exam)}, "
                                f"New room exists: {bool(room)}, "
                                f"Current room exists: {bool(existing_room)}."
                            ),
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # ✅ Get all student exams currently assigned to the existing room
                student_exams = StudentExam.objects.filter(
                    exam__in=exams, room=existing_room
                )

                if not student_exams.exists():
                    return Response(
                        {
                            "success": False,
                            "error_code": "NO_EXAMS_FOUND",
                            "message": (
                                f"No students found assigned to exam '{exam.course.name}' "
                                f"in room '{existing_room.name}'."
                            ),
                        },
                        status=status.HTTP_404_NOT_FOUND,
                    )

                # ✅ Calculate current occupancy in the target room
                current_room_occupancy = StudentExam.objects.filter(
                    room=room, exam__date=exam.date, exam__start_time=exam.start_time
                ).count()

                total_required_capacity = student_exams.count() + current_room_occupancy

                if room.capacity < total_required_capacity:
                    return Response(
                        {
                            "success": False,
                            "error_code": "ROOM_CAPACITY_EXCEEDED",
                            "message": (
                                f"Room '{room.name}' cannot accommodate this course group. "
                                f"Capacity ({room.capacity}) is insufficient for "
                                f"{total_required_capacity} students "
                                f"(including {current_room_occupancy} already assigned)."
                            ),
                        },
                        status=status.HTTP_412_PRECONDITION_FAILED,
                    )

                return Response(
                    {
                        "success": True,
                        "message": f"Room '{room.name}' is available and can accommodate this course group.",
                    },
                    status=status.HTTP_200_OK,
                )

        except Exception as e:
            return Response(
                {
                    "success": False,
                    "error_code": "INTERNAL_ERROR",
                    "message": f"An unexpected error occurred while verifying room change: {str(e)}",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["PATCH"], url_path="change_room")
    def change_room(self, request):
        try:

            with transaction.atomic():
                room = request.data.get("room")
                course_group = request.data.get("courseGroup")
                if not room or not course_group:
                    return Response(
                        {
                            "success": False,
                            "message": "Room and Course Group are required",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                # courseIds (plural) covers the occupancies view merging
                # several groups of the same course/room/slot into one card —
                # falls back to the single courseId any other caller sends.
                exam_ids = course_group.get("courseIds") or [course_group.get("courseId")]
                exams = Exam.objects.filter(id__in=exam_ids)
                room = Room.objects.filter(name=room["roomName"]).first()
                existingRoom = Room.objects.filter(
                    name=course_group["roomName"]
                ).first()
                if not exams.exists() or not room or not existingRoom:
                    return Response(
                        {
                            "success": False,
                            "message": "Invalid Room, existing romm and Course Group",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                student_exams = StudentExam.objects.filter(
                    exam__in=exams, room=existingRoom
                ).select_related("student__user", "exam__group__course")
                if not student_exams.exists():
                    return Response(
                        {
                            "success": False,
                            "message": "No student exams found for the specified exam and room",
                        },
                        status=status.HTTP_404_NOT_FOUND,
                    )
                is_actual_change = room.id != existingRoom.id
                room_changes = []
                for student_exam in student_exams:
                    if is_actual_change:
                        room_changes.append((student_exam, existingRoom, room))
                    student_exam.room = room
                    student_exam.save()
                if room_changes:
                    notify_students_room_changed(room_changes)
                return Response(
                    {"success": True, "message": "Exam room changed successfully"},
                    status=status.HTTP_201_CREATED,
                )
        except Exception as e:
            logger.error(f"Error while changing room occupancy: {e}", exc_info=True)
            return Response(
                {
                    "success": False,
                    "message": "An error occurred while changing room occupancy",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=["get"], url_path="occupancies")
    def room_occupancies(self, request):
        location = request.GET.get("location")
        timetable = request.GET.get("timetable")

        recent_timetable = None
        if timetable and location:
            recent_timetable = (
                MasterTimetable.objects.filter(id=timetable, location_id=location)
                .order_by("-created_at")
                .first()
            )
        elif location:
            recent_timetable = (
                MasterTimetable.objects.filter(location_id=location)
                .order_by("-created_at")
                .first()
            )
        elif timetable:
            recent_timetable = (
                MasterTimetable.objects.filter(id=timetable)
                .order_by("-created_at")
                .first()
            )

        if not recent_timetable:
            return Response(
                {
                    "success": True,
                    "data": [],
                    "message": "No timetable found",
                }
            )

        student_exams = (
            StudentExam.objects.filter(
                room__isnull=False,
                exam__group__course__department__location_id=recent_timetable.location.id,
            )
            .values(
                "room__id",
                "room__name",
                "room__capacity",
                "exam__id",
                "exam__group__course__code",
                "exam__group__course__title",
                "exam__group__course__department__name",
                "exam__group__group_name",
                "exam__group__course__semester__name",
                "exam__date",
                "exam__start_time",
                "exam__end_time",
                "exam__slot_name",
            )
            .annotate(student_count=Count("id"))
            .order_by("room__name", "exam__date", "exam__start_time")
        )

        # instructor is assigned per-student (StudentExam.instructor), not
        # per-exam, so including it in the values()/annotate() above used to
        # GROUP BY it too — any exam with students split across a couple of
        # instructor values (or unassigned vs assigned) got fragmented into
        # several separate occupancy rows with partial student_counts each,
        # instead of one row per exam. Looked up separately here, keyed by
        # room+slot, so the headcount grouping above stays exam-accurate.
        instructor_by_slot = {}
        instructor_rows = (
            StudentExam.objects.filter(
                room__isnull=False,
                instructor__isnull=False,
                exam__group__course__department__location_id=recent_timetable.location.id,
            )
            .values(
                "room__id",
                "exam__date",
                "exam__start_time",
                "exam__end_time",
                "instructor__id",
                "instructor__first_name",
                "instructor__last_name",
                "instructor__email",
            )
            .distinct()
        )
        for row in instructor_rows:
            key = (
                row["room__id"],
                row["exam__date"],
                row["exam__start_time"],
                row["exam__end_time"],
            )
            instructor_by_slot.setdefault(key, row)

        rooms = {}
        for item in student_exams:
            rid = item["room__id"]
            if rid not in rooms:
                rooms[rid] = {
                    "room_id": rid,
                    "room_name": item["room__name"],
                    "room_capacity": item["room__capacity"],
                    "schedules": [],
                }

            sched_list = rooms[rid]["schedules"]
            match = next(
                (
                    s
                    for s in sched_list
                    if s["date"] == item["exam__date"]
                    and s["start_time"] == item["exam__start_time"]
                    and s["end_time"] == item["exam__end_time"]
                ),
                None,
            )

            if not match:
                instructor_row = instructor_by_slot.get(
                    (
                        rid,
                        item["exam__date"],
                        item["exam__start_time"],
                        item["exam__end_time"],
                    )
                )
                match = {
                    "date": item["exam__date"],
                    "start_time": item["exam__start_time"],
                    "end_time": item["exam__end_time"],
                    "slot_name": item["exam__slot_name"],
                    "instructor": (
                        {
                            "id": instructor_row["instructor__id"],
                            "first_name": instructor_row["instructor__first_name"],
                            "last_name": instructor_row["instructor__last_name"],
                            "email": instructor_row["instructor__email"],
                        }
                        if instructor_row
                        else None
                    ),
                    "exams": [],
                }
                sched_list.append(match)

            match["exams"].append(
                {
                    "exam_id": item["exam__id"],
                    "course_code": item["exam__group__course__code"],
                    "course_title": item["exam__group__course__title"],
                    "course_department": item["exam__group__course__department__name"],
                    "course_group": item["exam__group__group_name"],
                    "course_semester": item["exam__group__course__semester__name"],
                    "student_count": item["student_count"],
                }
            )

        return Response(
            {
                "success": True,
                "data": list(rooms.values()),
                "message": "All room occupancies across scheduled exams",
            }
        )

    @action(detail=True, methods=["get"], url_path="seat_map")
    def seat_map(self, request, pk=None):
        room = self.get_object()

        date_str = request.GET.get("date")
        start_time_str = request.GET.get("start_time")
        end_time_str = request.GET.get("end_time")

        exam_date = parse_date(date_str) if date_str else None
        start_time = parse_time(start_time_str) if start_time_str else None
        end_time = parse_time(end_time_str) if end_time_str else None

        if not exam_date or not start_time or not end_time:
            return Response(
                {
                    "success": False,
                    "message": "Valid 'date', 'start_time' and 'end_time' query params are required",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        student_exams = StudentExam.objects.filter(
            room=room,
            exam__date=exam_date,
            exam__start_time=start_time,
            exam__end_time=end_time,
        ).select_related("student__user", "exam__group__course")

        if not room.has_seat_layout():
            return Response(
                {
                    "success": True,
                    "data": {
                        "room_id": room.id,
                        "room_name": room.name,
                        "capacity": room.capacity,
                        "rows": None,
                        "columns": None,
                        "seats": [],
                        "student_count": student_exams.count(),
                    },
                    "message": "This room has no seat layout (rows/columns) configured yet.",
                }
            )

        exam_colors = {}
        seats = []
        for se in student_exams:
            exam_id = se.exam_id
            if exam_id not in exam_colors:
                exam_colors[exam_id] = {
                    "color_index": len(exam_colors),
                    "course_code": se.exam.group.course.code,
                    "course_title": se.exam.group.course.title,
                    "course_group": se.exam.group.group_name,
                }
            seats.append(
                {
                    "row": se.seat_row,
                    "column": se.seat_column,
                    "student_exam_id": se.id,
                    "student": {
                        "id": se.student_id,
                        "reg_no": se.student.reg_no,
                        "first_name": se.student.user.first_name,
                        "last_name": se.student.user.last_name,
                    },
                    "exam_id": exam_id,
                    "course_code": exam_colors[exam_id]["course_code"],
                    "course_group": exam_colors[exam_id]["course_group"],
                    "color_index": exam_colors[exam_id]["color_index"],
                }
            )

        return Response(
            {
                "success": True,
                "data": {
                    "room_id": room.id,
                    "room_name": room.name,
                    "capacity": room.capacity,
                    "rows": room.rows,
                    "columns": room.columns,
                    "seats": seats,
                    "student_count": len(seats),
                    "legend": [
                        {"exam_id": exam_id, **info}
                        for exam_id, info in exam_colors.items()
                    ],
                },
                "message": "Seat map fetched successfully",
            }
        )

    @action(detail=True, methods=["get"], url_path="usage")
    def usage(self, request, pk=None):
        """
        Hotel-style day-by-day usage for a room: which dates have exam
        bookings (with course/group/slot detail) and which are blocked by a
        RoomOutOfService entry, over a date range (defaults to the next 30
        days from today).
        """
        room = self.get_object()

        start_str = request.GET.get("start")
        end_str = request.GET.get("end")
        start_date = parse_date(start_str) if start_str else timezone.localdate()
        end_date = (
            parse_date(end_str) if end_str else start_date + timedelta(days=30)
        )

        if not start_date or not end_date or start_date > end_date:
            return Response(
                {"success": False, "message": "Invalid 'start'/'end' date range"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bookings_by_date = defaultdict(list)
        exam_rows = (
            StudentExam.objects.filter(
                room=room, exam__date__range=(start_date, end_date)
            )
            .values(
                "exam__date", "exam__slot_name", "exam__start_time", "exam__end_time",
                "exam__group__course__code", "exam__group__course__title",
                "exam__group__group_name",
            )
            .annotate(student_count=Count("id"))
            .distinct()
        )
        for row in exam_rows:
            bookings_by_date[row["exam__date"]].append(
                {
                    "slot_name": row["exam__slot_name"],
                    "start_time": row["exam__start_time"],
                    "end_time": row["exam__end_time"],
                    "course_code": row["exam__group__course__code"],
                    "course_title": row["exam__group__course__title"],
                    "course_group": row["exam__group__group_name"],
                    "student_count": row["student_count"],
                }
            )

        blocks = RoomOutOfService.objects.filter(
            room=room, start_date__lte=end_date, end_date__gte=start_date
        )
        blocks_data = [
            {
                "id": b.id,
                "start_date": b.start_date,
                "end_date": b.end_date,
                "start_time": b.start_time,
                "end_time": b.end_time,
                "reason": b.reason,
            }
            for b in blocks
        ]

        days = []
        current = start_date
        while current <= end_date:
            day_blocks = [
                b for b in blocks_data
                if b["start_date"] <= current <= b["end_date"]
            ]
            days.append(
                {
                    "date": current,
                    "bookings": bookings_by_date.get(current, []),
                    "blocked": bool(day_blocks),
                    "blocks": day_blocks,
                }
            )
            current += timedelta(days=1)

        return Response(
            {
                "success": True,
                "data": {
                    "room_id": room.id,
                    "room_name": room.name,
                    "start_date": start_date,
                    "end_date": end_date,
                    "days": days,
                },
                "message": "Room usage fetched successfully",
            }
        )

    @action(detail=False, methods=["post"], url_path="verify")
    @permission_classes([])
    def verify_room_student(self, request, *args, **kwargs):
        try:
            tz = pytz_timezone(settings.TIME_ZONE)
            now = timezone.now().astimezone(tz)
            today = now.date()
            regNumber = request.data.get("regNumber")
            student_exam = StudentExam.objects.get(
                student__reg_no=regNumber,
                exam__date=today,
                exam__status__in=["READY", "ONGOING"],
            )
            serializer = StudentExamSerializer(student_exam)
            roomSerializer = RoomSerializer(student_exam.room)

            return Response(
                {
                    "success": True,
                    "exam": serializer.data,
                    "room": roomSerializer.data,
                    "message": "Your exam found",
                },
                status=status.HTTP_200_OK,
            )

        except StudentExam.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "message": "Your exam information will be available soon. Please check again later.",
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(f"Error while changing room occupancy: {e}", exc_info=True)
            return Response(
                {
                    "success": False,
                    "message": "An error occurred while changing room occupancy",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=["get"], url_path="configurations")
    @permission_classes([])
    def get_configurations(self, request, *args, **kwargs):
        try:
            locations = Location.objects.all()
            serializer = LocationSerializer(locations, many=True)
            semesters = Semester.objects.all()
            semesterSerializer = SemesterSerializer(semesters, many=True)
            configuration = {
                "locations": serializer.data,
                "semesters": semesterSerializer.data,
            }
            return Response(
                {
                    "data": configuration,
                    "success": True,
                    "message": "Exam configurations found successfully",
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {
                    "success": False,
                    "message": "An error occurred while fetching auca universtion default configurations.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=["get"], url_path="locations")
    @permission_classes([])
    def get_locations(self, request, *args, **kwargs):
        try:
            locations = Location.objects.all()
            serializer = LocationSerializer(locations, many=True)

            return Response(
                {
                    "data": serializer.data,
                    "success": True,
                    "message": "Locations found successfully found successfully",
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {
                    "success": False,
                    "message": "An error occurred while fetching auca universtion default locations.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=["post"], url_path="student_check")
    @permission_classes([])
    def verify_room(self, request, *args, **kwargs):
        try:
            tz = pytz_timezone(settings.TIME_ZONE)
            now = timezone.now().astimezone(tz)
            today = now.date()
            regNumber = request.data.get("regNumber")
            student_exam = StudentExam.objects.get(
                student__reg_no=regNumber,
                exam__date=today,
                exam__status__in=["READY", "ONGOING"],
            )
            serializer = StudentExamSerializer(student_exam)
            roomSerializer = RoomSerializer(student_exam.room)

            return Response(
                {
                    "success": True,
                    "exam": serializer.data,
                    "room": roomSerializer.data,
                    "message": "Your exam found",
                },
                status=status.HTTP_200_OK,
            )

        except StudentExam.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "message": "Your exam information will be available soon. Please check again later.",
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(f"Error while changing room occupancy: {e}", exc_info=True)
            return Response(
                {
                    "success": False,
                    "message": "An error occurred while changing room occupancy",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=["post"], url_path="assign_instructor")
    @permission_classes([])
    def assign_instructor(self, request, *args, **kwargs):
        try:
            instructor_id = request.data.get("instructor_id")
            room_id = request.data.get("room_id")
            timetable_id = request.data.get("timetable_id")
            date = request.data.get("date")
            slot_name = request.data.get("slot_name")
            date = parse_date(date) if date else None
            start_time = None
            end_time = None

            config_manager = JsonConfigManager()
            config = config_manager.read_config()
            time_config = config.get("time_constraints", {})
            time_slots = time_config.get("time_slots", [])
            if not timetable_id:
                return Response({"error": "timetable_id is required."}, status=400)

            try:
                timetable = MasterTimetable.objects.select_related(
                    "location", "semester"
                ).get(pk=timetable_id)
            except MasterTimetable.DoesNotExist:
                return Response({"error": "Timetable not found."}, status=404)
            for slot in time_slots:
                if slot.get("name", "").lower() == (slot_name or "").lower():
                    start_time = slot.get("start_time")
                    end_time = slot.get("end_time")
                    start_time = time.fromisoformat(start_time)
                    end_time = time.fromisoformat(end_time)
                    break

            if not instructor_id or not room_id or not date or not slot_name:
                return Response(
                    {
                        "success": False,
                        "message": "Instructor ID, Room ID, Date, and Slot Name are required",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not start_time or not end_time:
                return Response(
                    {
                        "success": False,
                        "message": f"Slot '{slot_name}' not found in configuration",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                instructor = User.objects.get(id=instructor_id)
            except User.DoesNotExist:
                return Response(
                    {
                        "success": False,
                        "message": "Invalid instructor",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            already_assigned = StudentExam.objects.filter(
                exam__date=date,
                exam__start_time=start_time,
                exam__end_time=end_time,
                instructor=instructor,
                student__department__location=timetable.location,
            ).exists()
            if already_assigned:
                return Response(
                    {
                        "success": False,
                        "message": "This instructor has already been assigned to another exam during the specified date and time slot",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            logger.info(
                f"Assigning instructor {instructor.get_full_name()} to exams in room ID {room_id} on {date} during slot '{slot_name}' ({start_time} - {end_time})"
            )

            student_exams_count = StudentExam.objects.filter(
                room__id=int(room_id),
                exam__date=date,
                exam__start_time=start_time,
                exam__end_time=end_time,
                student__department__location=timetable.location,
            ).update(instructor=instructor)

            if student_exams_count == 0:
                return Response(
                    {
                        "success": False,
                        "message": "No student exams found for the specified exam",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            return Response(
                {
                    "success": True,
                    "message": f"Successfully assigned instructor to {student_exams_count} student exam(s)",
                    "updated_count": student_exams_count,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {
                    "success": False,
                    "message": "An error occurred while assigning instructor",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["post"], url_path="instructor_check_qr")
    @permission_classes([])
    def instructor_room_qr(self, request, *args, **kwargs):
        try:

            room = request.data.get("name")
            tz = pytz_timezone(settings.TIME_ZONE)
            now = timezone.now().astimezone(tz)
            today = now.date()
            examRoom = Room.objects.filter(name=room).first()
            student_exams = StudentExam.objects.filter(
                exam__date=today,
                room=examRoom,
                exam__status__in=["READY", "ONGOING"],
            )
            students_info = []
            for student_exam in student_exams:
                enrollments = Enrollment.objects.filter(
                    student_id=student_exam.student.id
                )
                total_to_pay = sum(
                    enrollment.amount_to_pay for enrollment in enrollments
                )
                total_paid = sum(enrollment.amount_paid for enrollment in enrollments)
                all_paid = total_paid >= total_to_pay
                students_info.append(
                    {
                        "id": student_exam.student.user.id,
                        "reg_no": student_exam.student.reg_no,
                        "first_name": student_exam.student.user.first_name,
                        "last_name": student_exam.student.user.last_name,
                        "amount_to_pay": total_to_pay,
                        "amount_paid": total_paid,
                        "all_paid": all_paid,
                    }
                )

            return Response(
                {
                    "success": True,
                    "data": students_info,
                },
                status=200,
            )

        except Exception as e:
            return Response(
                {"success": False, "message": str(e)},
                status=500,
            )

    @action(detail=False, methods=["post"], url_path="student_check_qr")
    @permission_classes([])
    def verify_room_qr(self, request, *args, **kwargs):
        try:
            student = request.user.student
            room = request.data.get("name")
            tz = pytz_timezone(settings.TIME_ZONE)
            now = timezone.now().astimezone(tz)
            today = now.date()
            regNumber = student.reg_no
            examRoom = Room.objects.filter(name=room).first()
            student_exam = StudentExam.objects.get(
                student__reg_no=regNumber,
                exam__date=today,
                room=examRoom,
                exam__status__in=["READY", "ONGOING"],
            )

            if student_exam.signin_attendance and student_exam.room==examRoom:
                return Response(
                    {
                        "success": True,
                        "data": {
                            "status": True,
                            "studentName": f"{student.user.first_name} {student.user.last_name}",
                            "studentRegNumber": student.reg_no,
                            "message": f"Now you have {student_exam.exam.group.course.title} in this room {student_exam.room.name}.",
                        },
                    },
                    status=200,
                )

            

            enrollments = Enrollment.objects.filter(student_id=student.id)

            if not enrollments.exists():
                return Response(
                    {
                        "success": False,
                        "message": "No enrolled courses found for this student.",
                    },
                    status=404,
                )

            # Calculate totals across all enrollments
            total_to_pay = sum(enrollment.amount_to_pay for enrollment in enrollments)
            total_paid = sum(enrollment.amount_paid for enrollment in enrollments)
            all_paid = total_paid >= total_to_pay

            if all_paid:
                student_exam.signin_attendance = True
                student_exam.save()
                return Response(
                    {
                        "success": True,
                        "data": {
                            "status": True,
                            "studentName": f"{student.user.first_name} {student.user.last_name}",
                            "studentRegNumber": student.reg_no,
                            "message": f"Now you have {student_exam.exam.group.course.title} in room {student_exam.room.name}",
                        },
                    },
                    status=200,
                )
            else:
                return Response(
                    {
                        "success": False,
                        "data": {
                            "status": False,
                            "message": f"Now you have {student_exam.exam.group.course.title} in room {student_exam.room.name} but  You haven't paid for all courses",
                            "studentName": f"{student.user.first_name} {student.user.last_name}",
                            "studentRegNumber": student.reg_no,
                            "amountToPay": total_to_pay,
                            "amountPaid": total_paid,
                        },
                    },
                    status=200,
                )

        except StudentExam.DoesNotExist:
            try:
                student_exam = StudentExam.objects.get(
                    student__reg_no=regNumber,
                    exam__date=today,
                    exam__status__in=["READY", "ONGOING"],
                )

                enrollments = Enrollment.objects.filter(student_id=student.id)

                if not enrollments.exists():
                    return Response(
                        {
                            "success": False,
                            "message": "No enrolled courses found for this student.",
                        },
                        status=404,
                    )

                # Calculate totals across all enrollments
                total_to_pay = sum(
                    enrollment.amount_to_pay for enrollment in enrollments
                )
                total_paid = sum(enrollment.amount_paid for enrollment in enrollments)
                all_paid = total_paid >= total_to_pay

                if all_paid:
                    return Response(
                        {
                            "success": False,
                            "data": {
                                "status": False,
                                "studentName": f"{student.user.first_name} {student.user.last_name}",
                                "studentRegNumber": student.reg_no,
                                "message": f"Now you have {student_exam.exam.group.course.title} in room {student_exam.room.name} but you've scanned on Wrong room",
                            },
                        },
                        status=200,
                    )
                else:
                    return Response(
                        {
                            "success": False,
                            "data": {
                                "status": False,
                                "message": f"Now you have {student_exam.exam.group.course.title} in room {student_exam.room.name} but  You haven't paid for all courses",
                                "studentName": f"{student.user.first_name} {student.user.last_name}",
                                "studentRegNumber": student.reg_no,
                                "amountToPay": total_to_pay,
                                "amountPaid": total_paid,
                            },
                        },
                        status=200,
                    )
            except StudentExam.DoesNotExist:

                return Response(
                    {
                        "success": False,
                        "message": "Your exam information will be available soon. Please check again later.",
                    },
                    status=status.HTTP_200_OK,
                )

        except Exception as e:
            logger.error(f"Error while changing room occupancy: {e}", exc_info=True)
            return Response(
                {
                    "success": False,
                    "message": "An error occurred while changing room occupancy",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )


class RoomAllocationSwitchViewSet(viewsets.ModelViewSet):
    queryset = RoomAllocationSwitch.objects.all()
    serializer_class = RoomAllocationSwitchSerializer

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [permissions.IsAdminUser]
        return [permission() for permission in permission_classes]

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
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
                "message": "Fetched successfully",
            }
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {
                "success": True,
                "data": serializer.data,
                "message": "Created successfully",
            },
            status=status.HTTP_201_CREATED,
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
                "message": "Updated successfully",
            }
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(
            {"success": True, "message": "Deleted successfully"},
            status=status.HTTP_204_NO_CONTENT,
        )


class RoomOutOfServiceViewSet(viewsets.ModelViewSet):
    queryset = RoomOutOfService.objects.select_related("room", "created_by").all()
    serializer_class = RoomOutOfServiceSerializer
    permission_classes = [RoomsIsAdminOrInstructor]

    def get_queryset(self):
        queryset = super().get_queryset()
        room_id = self.request.GET.get("room")
        if room_id:
            queryset = queryset.filter(room_id=room_id)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {"success": True, "data": serializer.data, "message": "Fetched successfully"}
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {"success": True, "data": serializer.data, "message": "Room blocked successfully"},
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(
            {"success": True, "data": serializer.data, "message": "Updated successfully"}
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(
            {"success": True, "message": "Room block removed successfully"},
            status=status.HTTP_204_NO_CONTENT,
        )
