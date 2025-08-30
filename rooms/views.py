from pprint import pprint
from django.conf import settings
from django.shortcuts import render

from rest_framework import viewsets, status, permissions
from rest_framework.response import Response

from courses.serializers import CourseSerializer, SemesterSerializer
from enrollments.models import Enrollment
from exams.serializers import StudentExamSerializer
from schedules.models import MasterTimetable
from schedules.utils import get_occupied_seats_by_time_slot
from semesters.models import Semester
from .models import Location, Room, RoomAllocationSwitch
from rest_framework.decorators import action, permission_classes
from .serializers import LocationSerializer, RoomSerializer, RoomAllocationSwitchSerializer
from django.contrib.auth import get_user_model
from exams.models import Exam, StudentExam
from django.db.models import Count
from collections import defaultdict
from django.db import transaction
from django.utils import timezone
from django.db.models import Sum
from django.utils.dateparse import parse_date
from pytz import timezone as pytz_timezone

User = get_user_model()


# Create your views here.
class RoomViewSet(viewsets.ModelViewSet):
    queryset = Room.objects.all()
    serializer_class = RoomSerializer

    def get_permissions(self):
        if self.action in["verify_room", "verify_room_qr", "instructor_room_qr"]:
            return []  # No permissions required
        elif self.action in ["list", "retrieve"]:
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
                exam = Exam.objects.filter(id=course_group["courseId"]).first()

                existingRoom = Room.objects.filter(
                    name=course_group["roomName"]
                ).first()
                if not exam or not existingRoom:
                    return Response(
                        {
                            "success": False,
                            "message": "Invalid Room, existing romm and Course Group",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                student_exams = StudentExam.objects.filter(exam=exam, room=existingRoom)
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
                student_exams = StudentExam.objects.filter(id__in=exams)

                if not student_exams.exists():
                    return Response(
                        {
                            "success": False,
                            "message": "No student exams found for the specified exam and room",
                        },
                        status=status.HTTP_404_NOT_FOUND,
                    )
                for student_exam in student_exams:
                    student_exam.room = room
                    student_exam.save()
                return Response(
                    {"success": True, "message": "Exam room changed successfully"},
                    status=status.HTTP_201_CREATED,
                )
        except:
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
                exam = Exam.objects.filter(id=course_group.get("courseId")).first()
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
                    exam=exam, room=existing_room
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
                exam = Exam.objects.filter(id=course_group["courseId"]).first()
                room = Room.objects.filter(name=room["roomName"]).first()
                existingRoom = Room.objects.filter(
                    name=course_group["roomName"]
                ).first()
                if not exam or not room or not existingRoom:
                    return Response(
                        {
                            "success": False,
                            "message": "Invalid Room, existing romm and Course Group",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                student_exams = StudentExam.objects.filter(exam=exam, room=existingRoom)
                if not student_exams.exists():
                    return Response(
                        {
                            "success": False,
                            "message": "No student exams found for the specified exam and room",
                        },
                        status=status.HTTP_404_NOT_FOUND,
                    )
                for student_exam in student_exams:
                    student_exam.room = room
                    student_exam.save()
                return Response(
                    {"success": True, "message": "Exam room changed successfully"},
                    status=status.HTTP_201_CREATED,
                )
        except:
            return Response(
                {
                    "success": False,
                    "message": "An error occurred while changing room occupancy",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=["get"], url_path="occupancies")
    def room_occupancies(self, request):
        location= request.GET.get("location")
       

        recent_timetable = MasterTimetable.objects.order_by("-created_at").first()
        if location:
            recent_timetable=MasterTimetable.objects.filter(location_id=location).order_by("-created_at").first()
        student_exams = (
            StudentExam.objects.filter(room__isnull=False, exam__group__course__department__location_id=recent_timetable.location.id)
            .values(
                "room__id",
                "room__name",
                "room__capacity",
                "exam__id",
                # COURSE FIELDS
                "exam__group__course__code",
                "exam__group__course__title",
                "exam__group__course__department__name",
                "exam__group__group_name",  # ← use the exam’s own group
                "exam__group__course__semester__name",
                # SCHEDULING
                "exam__date",
                "exam__start_time",
                "exam__end_time",
                "exam__slot_name",
                # Instructor
                "instructor__id",
                "instructor__first_name",
                "instructor__last_name",
                "instructor__email",
            )
            .annotate(student_count=Count("id"))
            .order_by("room__name", "exam__date", "exam__start_time")
        )

        rooms = {}
        for item in student_exams:
            rid = item["room__id"]
            if rid not in rooms:
                rooms[rid] = {
                    "room_id": rid,
                    "room_name": item["room__name"],
                    "room_capacity": item["room__capacity"],
                    "schedules": [],
                      "instructor": {
                        "id": item["instructor__id"],
                        "first_name": item["instructor__first_name"],
                        "last_name": item["instructor__last_name"],
                        "email": item["instructor__email"],
                    } if item["instructor__id"] else None,
                    "slot_name": item["exam__slot_name"],
                }

            # find or create this slot
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
                match = {
                    "date": item["exam__date"],
                    "start_time": item["exam__start_time"],
                    "end_time": item["exam__end_time"],
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

    @action(detail=False, methods=["post"], url_path="verify")
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

        except:
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
            locations= Location.objects.all()
            serializer= LocationSerializer(locations, many=True)
            semesters= Semester.objects.all()
            semesterSerializer= SemesterSerializer(semesters, many=True)
            configuration={
                "locations":serializer.data,
                "semesters":semesterSerializer.data
            }
            return Response(
                {
                    "data":configuration,
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
            locations= Location.objects.all()
            serializer= LocationSerializer(locations, many=True)
           
          
            return Response(
                {
                    "data":serializer.data,
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

        except:
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
            # Extract and validate required fields
            instructor_id = request.data.get("instructor_id")
            room_id = request.data.get("room_id")
            date= request.data.get("date")
            slot_name= request.data.get("slot_name")
            date = parse_date(date) if date else None

            
            if not instructor_id or not room_id or not date or not slot_name:
                return Response({
                    "success": False,
                    "message": "Instructor ID, Room ID, Date, and Slot Name are required",
                }, status=status.HTTP_400_BAD_REQUEST)

            # Use select_related to optimize database queries and check existence
            try:
                instructor = User.objects.get(id=instructor_id)
            except User.DoesNotExist:
                return Response({
                    "success": False,
                    "message": "Invalid instructor",
                }, status=status.HTTP_404_NOT_FOUND)
        
            
            print(room_id, type(room_id), date, type(date), slot_name, type(slot_name))

            # Check if student exams exist and update in bulk
            student_exams_count = StudentExam.objects.filter(room__id= int(room_id), exam__date=date, exam__slot_name=slot_name).update(
                instructor=instructor
            )
            
            if student_exams_count == 0:
                return Response({
                    "success": False,
                    "message": "No student exams found for the specified exam",
                }, status=status.HTTP_404_NOT_FOUND)

            return Response({
                "success": True,
                "message": f"Successfully assigned instructor to {student_exams_count} student exam(s)",
                "updated_count": student_exams_count,
            }, status=status.HTTP_200_OK)

        except Exception as e:
            # Log the actual error for debugging (consider using proper logging)
            return Response({
                "success": False,
                "message": "An error occurred while assigning instructor",
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
                # exam__status__in=["READY", "ONGOING"],
            )
            students_info = []
            for student_exam in student_exams:
                enrollments = Enrollment.objects.filter(student_id=student_exam.student.id)
                total_to_pay = sum(
                    enrollment.amount_to_pay for enrollment in enrollments
                )
                total_paid = sum(enrollment.amount_paid for enrollment in enrollments)
                all_paid = total_to_pay == total_paid
                students_info.append(
                    {
                        "id": student_exam.student.user.id,
                        "reg_no": student_exam.student.reg_no, "first_name": student_exam.student.user.first_name,
                        "last_name":student_exam.student.user.last_name,
                        "amount_to_pay":total_to_pay,
                        "amount_paid":total_paid,
                        "all_paid":all_paid
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
                {
                    "success": False,
                     "message": str(e)
                },
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
                # exam__status__in=["READY", "ONGOING"],
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
            all_paid = total_to_pay == total_paid

            if all_paid:
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
                    # exam__status__in=["READY", "ONGOING"],
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
                all_paid = total_to_pay == total_paid
 

                if all_paid:
                    return Response(
                        {
                            "success": False,
                            "data": {
                                "status": False,
                                "studentName": f"{student.user.first_name} {student.user.last_name}",
                                "studentRegNumber": student.reg_no,
                                "message": f"Now you have {student_exam.exam.group.course.title} in room {student_exam.room.name} but you've scanned on Wrong room", },
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

        except:
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
