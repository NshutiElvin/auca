from django.shortcuts import render

from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from .models import Room, RoomAllocationSwitch
from rest_framework.decorators import action
from .serializers import RoomSerializer, RoomAllocationSwitchSerializer
from django.contrib.auth import get_user_model
from exams.models import StudentExam
from django.db.models import Count
from collections import defaultdict
User = get_user_model()
# Create your views here.
class RoomViewSet(viewsets.ModelViewSet):
    queryset = Room.objects.all()
    serializer_class = RoomSerializer
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [permissions.IsAdminUser]
        return [permission() for permission in permission_classes]

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response({"success": True, "data": serializer.data, "message": "Fetched successfully"})

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({"success": True, "data": serializer.data, "message": "Fetched successfully"})

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response({"success": True, "data": serializer.data, "message": "Created successfully"}, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response({"success": True, "data": serializer.data, "message": "Updated successfully"})

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response({"success": True, "message": "Deleted successfully"}, status=status.HTTP_204_NO_CONTENT)
    @action(detail=False, methods=['get'], url_path='occupancies')
    def room_occupancies(self, request):
        """
        Get current student occupancies for all rooms across all scheduled exams,
        grouped by room and exam slot (date + time).
        """
        student_exams = (
            StudentExam.objects
            .filter(room__isnull=False)
            .values(
                'room__id', 'room__name',"room__capacity",
                'exam__id', 'exam__course__code','exam__course__title',
                'exam__course__department__name',
                'exam__course__group',
                'exam__course__semester__name',

                'exam__date', 'exam__start_time', 'exam__end_time'
            )
            .annotate(student_count=Count('id'))
            .order_by('room__name', 'exam__date', 'exam__start_time')
        )

        # Structure: {room_id: {room info + schedules list}}
        rooms = {}

        for item in student_exams:
            room_id = item['room__id']
            room_name = item['room__name']
            room_capacity = item['room__capacity']  
            exam_date = item['exam__date']
            start_time = item['exam__start_time']
            end_time = item['exam__end_time']

            # Initialize room entry
            if room_id not in rooms:
                rooms[room_id] = {
                    "room_id": room_id,
                    "room_name": room_name,
                    "room_capacity": room_capacity,
                    "schedules": []
                }

            # Check if a schedule (slot) already exists
            room_schedules = rooms[room_id]['schedules']
            matching_schedule = next(
                (s for s in room_schedules if s['date'] == exam_date and s['start_time'] == start_time and s['end_time'] == end_time),
                None
            )

            # If not found, add new schedule
            if not matching_schedule:
                matching_schedule = {
                    "date": exam_date,
                    "start_time": start_time,
                    "end_time": end_time,
                    
                    "exams": []
                }
                room_schedules.append(matching_schedule)

            # Add exam to schedule
            matching_schedule['exams'].append({
                "exam_id": item['exam__id'],
                "course_code": item['exam__course__code'],
                "student_count": item['student_count'],
                "course_title":item['exam__course__title'],
                "course_department":item["exam__course__department__name"],
                "course_semester":item['exam__course__semester__name'],
                "course_group":item['exam__course__group']
            })

        return Response({
            "success": True,
            "data": list(rooms.values()),
            "message": "All room occupancies across scheduled exams"
        })

class RoomAllocationSwitchViewSet(viewsets.ModelViewSet):
    queryset = RoomAllocationSwitch.objects.all()
    serializer_class = RoomAllocationSwitchSerializer
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [permissions.IsAdminUser]
        return [permission() for permission in permission_classes]

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response({"success": True, "data": serializer.data, "message": "Fetched successfully"})

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({"success": True, "data": serializer.data, "message": "Fetched successfully"})

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response({"success": True, "data": serializer.data, "message": "Created successfully"}, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response({"success": True, "data": serializer.data, "message": "Updated successfully"})

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response({"success": True, "message": "Deleted successfully"}, status=status.HTTP_204_NO_CONTENT)
    