 
from rest_framework import serializers, viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from .models import  Room, Student, Course, Exam, StudentExam
from .serializers import ExamSerializer, StudentExamSerializer
from django.shortcuts import render
from schedules.utils import generate_exam_schedule # cancel_exam, reschedule_exam
from .permissions import IsAdminOrInstructor
from django.db import transaction
from django.db.models import Count
from enrollments.models import Enrollment

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
    
            start_date_str = request.data.get('start_date')
            course_ids = request.data.get('course_ids', None)
            semesterd=request.data.get('semester', None)
            # print(semester)
            if start_date_str and "T" in start_date_str:
                start_date_str = start_date_str.split("T")[0] 

            start_date = parse_date(start_date_str) if start_date_str else None
            # course_ids = list(map(int, course_ids)) if course_ids else None
            
        #     course_ids = (
        #     Enrollment.objects
        #     .filter(course__semester=semesterd)
        #     .values('course_id')                      # Get course IDs
        #     .annotate(enrollment_count=Count('id'))   # Count enrollments per course
        #     .filter(enrollment_count__gt=1)           # Keep those with >1 enrollment
        #     .values_list('course_id', flat=True)      # Extract course IDs as list
        # )
            print(course_ids)

            exams,_ = generate_exam_schedule(start_date=start_date, course_ids=course_ids, semester=None)
            queryset = self.filter_queryset(self.get_queryset())
            serializer = self.get_serializer(queryset, many=True)
            return Response({
                'success': True,
                'message': f'{len(exams)} exams scheduled successfully.',
                "data": serializer.data
            })
     
    @action(detail=False, methods=['post'], url_path='cancel-exam')
    def cancel_exam_view(self, request):
        try:
            exam_id = request.data.get('exam_id')
            if not exam_id:
                return Response({
                    'success': False,
                    'message': 'Missing exam_id'
                }, status=status.HTTP_400_BAD_REQUEST)

            # cancel_exam(exam_id)
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
            slot= request.data.get('slot', None)

            if not (exam_id and new_date_str):
                return Response({
                    'success': False,
                    'message': 'Missing required fields: exam_id, new_date'
                }, status=status.HTTP_400_BAD_REQUEST)

            new_date = parse_date(new_date_str)
            # updated_exam = reschedule_exam(
            #     exam_id=exam_id,
            #     new_date=new_date,
            #     slot=slot
            # )
            queryset = self.filter_queryset(self.get_queryset())
            serializer = self.get_serializer(queryset, many=True)
            return Response({
                'success': True,
                'message': f'Exam {exam_id} rescheduled successfully',
                "data": serializer.data
            })
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error rescheduling exam: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)
    @action(detail=False, methods=['delete'], url_path='truncate-all', permission_classes=[permissions.IsAuthenticated])
    def truncate_all(self, request):
        try:
            with transaction.atomic():
                StudentExam.objects.all().delete()
                Exam.objects.all().delete()
            return Response({
                'success': True,
                'message': 'All exams and student exam assignments have been truncated successfully.'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error truncating data: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class StudentExamViewSet(viewsets.ModelViewSet):
    queryset = StudentExam.objects.select_related('student', 'exam', 'room').all()
    serializer_class = StudentExamSerializer
    # permission_classes=[permissions.IsAuthenticated]
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [permissions.IsAuthenticated]
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
    @action(detail=False, methods=['get'], url_path='mine')
    def mine(self, request, *args, **kwargs):
        try:
            student = request.user.student  
            
        except Student.DoesNotExist:
            return Response({
                "success": False,
                "message": "Student profile not found for this user."
            }, status=404)

        exams = StudentExam.objects.filter(student=student)
        serializer = StudentExamSerializer(exams, many=True)
        return Response({
            "success": True,
            "data": serializer.data,
            "message": "Fetched successfully"
        })
    
    @action(detail=False, methods=['post'], url_path='verify')
    def verify(self, request, *args, **kwargs):
        try:
             
            print(request.data)
            
            
        except :
            return Response({
                "success": False,
                "message": "Student profile not found for this user."
            }, status=404)

        # exams = StudentExam.objects.filter(student=student)
        # serializer = StudentExamSerializer(exams, many=True)
        return Response({
            "success": True,
            "data": "",
            "message": "Fetched successfully"
        })
    