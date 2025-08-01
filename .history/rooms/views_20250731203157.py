from pprint import pprint
from django.shortcuts import render

from rest_framework import viewsets, status, permissions
from rest_framework.response import Response

from exams.serializers import StudentExamSerializer
from schedules.utils import get_occupied_seats_by_time_slot
from .models import Room, RoomAllocationSwitch
from rest_framework.decorators import action
from .serializers import RoomSerializer, RoomAllocationSwitchSerializer
from django.contrib.auth import get_user_model
from exams.models import Exam, StudentExam
from django.db.models import Count
from collections import defaultdict
from django.db import transaction
from django.db.models import Sum

User = get_user_model()


# Create your views here.
class RoomViewSet(viewsets.ModelViewSet):
    queryset = Room.objects.all()
    serializer_class = RoomSerializer

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
                print(request.data)
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
                    print(exam, room, existingRoom)
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
                current_room_occuapncy= StudentExam.objects.filter(room=room, date= exam.date, exam__start_time= exam.start_time).count()
                if room.capacity < student_exams.count() + current_room_occuapncy:
                    return Response(
                    {"success": False, "message": f"Room {room.name} can't accommodate this exam because of limited capacity"},
                    status=status.HTTP_412_PRECONDITION_FAILED,
                )
                else:
                      return Response(
                    {"success": True, "message": f"Room {room.name} can accomodate this course"},
                    status=status.HTTP_200_OK,
                )


          
                 
        except Exception as e:
            print(e)
            return Response(
                {
                    "success": False,
                    "message": "An error occurred while changing room occupancy",
                },
                status=status.HTTP_400_BAD_REQUEST,
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
        student_exams = (
            StudentExam.objects.filter(room__isnull=False)
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
                    "course_group": item["exam__group__group_name"],  # ← corrected
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
