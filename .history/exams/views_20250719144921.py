 
from datetime import datetime
from rest_framework import serializers, viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from .models import  Student, Exam, StudentExam
from .serializers import ExamSerializer, StudentExamSerializer
from schedules.utils import   generate_exam_schedule  
from django.db import transaction
from django.db.models import Count
from enrollments.models import Enrollment
from student.models import Student
from courses.serializers import CourseSerializer

from django.utils.dateparse import parse_date
class ExamViewSet(viewsets.ModelViewSet):
    queryset = Exam.objects.select_related('group', 'room').all()
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
            end_date_str = request.data.get('end_date')
            course_ids = request.data.get('course_ids', None)
            # print(semester)
            if start_date_str and "T" in start_date_str:
                start_date_str = start_date_str.split("T")[0] 
            if end_date_str and "T" in end_date_str:
                end_date_str = end_date_str.split("T")[0] 

            start_date = parse_date(start_date_str) if start_date_str else None
            end_date = parse_date(end_date_str) if end_date_str else None
            print(start_date)

             
            exams,unaccomodated, unscheduled = generate_exam_schedule(start_date=start_date,end_date=end_date, course_ids=course_ids, semester=None)
            queryset = self.filter_queryset(self.get_queryset())
            serializer = self.get_serializer(queryset, many=True)
            return Response({
                'success': True,
                'message': f'{len(exams)} exams scheduled successfully.',
                "data": serializer.data,
                "unaccomodated":unaccomodated,
                "unscheduled":unscheduled
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

            data= request.data
            student_id = data.get("studentId")
            course_id= data.get("courseId")
            student=  Student.objects.get(user_id= student_id)
            # get student enrollment from database for checkng payment status
            student_enrollment= Enrollment.objects.filter(student_id= student.id, course_id=int(course_id)).first()
            # check if student has paid for course
            amount_to_pay= student_enrollment.amount_to_pay
            amount_paid= student_enrollment.amount_paid
            course_serializer= CourseSerializer(student_enrollment.course)

            if amount_to_pay!=amount_paid:
                return Response({
                "success": False,
                "data":{
                    "status":False,
                    "message": "You haven't for the course",
                    "course": course_serializer.data,
                    "studentName": f"{student.user.first_name} {student.user.last_name}",
                    "studentRegNumber":student.reg_no,
                    "amountToPay":amount_to_pay,
                    "amountPaid": amount_paid

                },
            }, status=200)
            else:
                return Response({
                "success": False,
                "data":{
                    "status":True,
                    "message": "You have paid your full payment",
                    "course": course_serializer.data,
                    "studentName": f"{student.user.first_name} {student.user.last_name}",
                    "studentRegNumber":student.reg_no,
                    "amountToPay":amount_to_pay,
                    "amountPaid": amount_paid

                },
            }, status=200)
            
            
        except Student.DoesNotExist :
            return Response({
                "success": False,
                "message": "Student profile not found for this user."
            }, status=404)

       
    