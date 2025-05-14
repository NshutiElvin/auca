 
from rest_framework import serializers, viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from django.contrib.auth import get_user_model
from .models import  Room, Student, Course, Exam, StudentExam
from .serializers import ExamSerializer, StudentExamSerializer
from django.shortcuts import render
from schedules.utils import generate_exam_schedule, cancel_exam, reschedule_exam
from .permissions import IsAdminOrInstructor

from django.utils.dateparse import parse_date
class ExamViewSet(viewsets.ModelViewSet):
    queryset = Exam.objects.select_related('course', 'room').all()
    serializer_class = ExamSerializer
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [permissions.IsAdminUser]
        return [permission() for permission in permission_classes]

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        for exam in queryset:
            exam.update_status()
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
    
    @action(detail=False, methods=['post'], url_path='generate-exam-schedule')
    def generate_exam_schedule_view(self, request):
        try:
            start_date_str = request.data.get('start_date')
            course_ids = request.data.get('course_ids', None)
            if start_date_str and "T" in start_date_str:
                start_date_str = start_date_str.split("T")[0] 

            start_date = parse_date(start_date_str) if start_date_str else None
            course_ids = list(map(int, course_ids)) if course_ids else None

            exams,_ = generate_exam_schedule(start_date=start_date, course_ids=course_ids)
            return Response({
                'success': True,
                'message': f'{len(exams)} exams scheduled successfully.',
                'data': [{'id': e.id, 'course': e.course.code, 'date': e.date} for e in exams]
            })
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error scheduling exams: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='cancel-exam')
    def cancel_exam_view(self, request):
        try:
            exam_id = request.data.get('exam_id')
            if not exam_id:
                return Response({
                    'success': False,
                    'message': 'Missing exam_id'
                }, status=status.HTTP_400_BAD_REQUEST)

            cancel_exam(exam_id)
            return Response({
                'success': True,
                'message': f'Exam {exam_id} cancelled successfully'
            })
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error cancelling exam: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='reschedule-exam')
    def reschedule_exam_view(self, request):
        try:
            exam_id = request.data.get('exam_id')
            new_date_str = request.data.get('new_date')
            new_start_time = request.data.get('new_start_time', None)
            new_end_time = request.data.get('new_end_time', None)

            if not (exam_id and new_date_str):
                return Response({
                    'success': False,
                    'message': 'Missing required fields: exam_id, new_date'
                }, status=status.HTTP_400_BAD_REQUEST)

            new_date = parse_date(new_date_str)
            updated_exam = reschedule_exam(
                exam_id=exam_id,
                new_date=new_date,
                new_start_time=new_start_time,
                new_end_time=new_end_time
            )
            return Response({
                'success': True,
                'message': f'Exam {exam_id} rescheduled successfully',
                'data': {
                    'id': updated_exam.id,
                    'course': updated_exam.course.code,
                    'date': updated_exam.date,
                    'start_time': updated_exam.start_time,
                    'end_time': updated_exam.end_time
                }
            })
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error rescheduling exam: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)

class StudentExamViewSet(viewsets.ModelViewSet):
    queryset = StudentExam.objects.select_related('student', 'exam', 'room').all()
    serializer_class = StudentExamSerializer

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
    
  