from django.shortcuts import render

from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from .models import Room, RoomAllocationSwitch
from rest_framework.decorators import action
from .serializers import RoomSerializer, RoomAllocationSwitchSerializer
from django.contrib.auth import get_user_model
from exams.models import Exam, StudentExam
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
    @action(detail=False, methods=['PATCH'], url_path='change_room')
    def change_room(self, request):
        try:
            room= request.data.get('room')
            course_group= request.data.get('courseGroup')
            if not room or not course_group:
                return Response({"success": False, "message": "Room and Course Group are required"}, status=status.HTTP_400_BAD_REQUEST)
            exam = Exam.objects.filter(id=course_group["courseId"]).first()
            room= Room.objects.filter(name= room["roomName"]).first()
            if not exam or not room:
                return Response({"success": False, "message": "Invalid Room or Course Group"}, status=status.HTTP_400_BAD_REQUEST)
            print(exam)
            print(room)
            return Response({"success": True, "message": "This endpoint is not implemented yet"}, status=status.HTTP_200_OK)
        except:
            return Response({"success": False, "message": "An error occurred while changing room occupancy"}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'], url_path='occupancies')
    def room_occupancies(self, request):
        student_exams = (
            StudentExam.objects
            .filter(room__isnull=False)
            .values(
                'room__id', 'room__name', 'room__capacity',
                'exam__id',
                # COURSE FIELDS
                'exam__group__course__code',
                'exam__group__course__title',
                'exam__group__course__department__name',
                'exam__group__group_name',      # ← use the exam’s own group
                'exam__group__course__semester__name',
                # SCHEDULING
                'exam__date', 'exam__start_time', 'exam__end_time',
            )
            .annotate(student_count=Count('id'))
            .order_by('room__name', 'exam__date', 'exam__start_time')
        )

        rooms = {}
        for item in student_exams:
            rid = item['room__id']
            if rid not in rooms:
                rooms[rid] = {
                    'room_id': rid,
                    'room_name': item['room__name'],
                    'room_capacity': item['room__capacity'],
                    'schedules': []
                }

            # find or create this slot
            sched_list = rooms[rid]['schedules']
            match = next((
                s for s in sched_list
                if s['date'] == item['exam__date']
                   and s['start_time'] == item['exam__start_time']
                   and s['end_time']   == item['exam__end_time']
            ), None)

            if not match:
                match = {
                    'date': item['exam__date'],
                    'start_time': item['exam__start_time'],
                    'end_time': item['exam__end_time'],
                    'exams': []
                }
                sched_list.append(match)

            match['exams'].append({
                'exam_id': item['exam__id'],
                'course_code': item['exam__group__course__code'],
                'course_title': item['exam__group__course__title'],
                'course_department': item['exam__group__course__department__name'],
                'course_group': item['exam__group__group_name'],           # ← corrected
                'course_semester': item['exam__group__course__semester__name'],
                'student_count': item['student_count'],
            })

        return Response({
            'success': True,
            'data': list(rooms.values()),
            'message': 'All room occupancies across scheduled exams'
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
    