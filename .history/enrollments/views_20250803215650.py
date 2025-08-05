from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from .models import    Enrollment
from .serializers import (
 
    EnrollmentSerializer,
)
from .permissions import  IsStudent
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter
from rest_framework.decorators import action
from student.models import Student
 


class EnrollmentViewSet(viewsets.ModelViewSet):
    queryset = Enrollment.objects.select_related('student', 'course')
    serializer_class = EnrollmentSerializer
    basename = 'enrollment'
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['course', 'student', 'status', 'enrollment_date']
    search_fields = ['student__username', 'course__code', 'course__title']
    ordering_fields = ['enrollment_date', 'status', 'final_grade']
    ordering = ['-enrollment_date']

    """
    Base ViewSet to format responses consistently
    """
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'success': True,
            'data': serializer.data,
            'message': f'{self.basename.title()}s fetched successfully'
        })

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({
            'success': True,
            'data': serializer.data,
            'message': f'{self.basename.title()} fetched successfully'
        })

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response({
            'success': True,
            'data': serializer.data,
            'message': f'{self.basename.title()} created successfully'
        }, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response({
            'success': True,
            'data': serializer.data,
            'message': f'{self.basename.title()} updated successfully'
        })

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response({
            'success': True,
            'message': f'{self.basename.title()} deleted successfully'
        }, status=status.HTTP_204_NO_CONTENT)

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated()]
        return [IsStudent()]
    @action(detail=False, methods=['get'], url_path='mine')
    def mine(self, request, *args, **kwargs):
        try:
            student = request.user.student  
            
        except Student.DoesNotExist:
            return Response({
                "success": False,
                "message": "Student profile not found for this user."
            }, status=404)

        enrollments = Enrollment.objects.filter(student=student)
        serializer = EnrollmentSerializer(enrollments, many=True)
        return Response({
            "success": True,
            "data": serializer.data,
            "message": "Fetched successfully"
        })