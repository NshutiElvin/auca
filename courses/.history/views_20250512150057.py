from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from .models import Department, Semester, Course, CourseSchedule, Enrollment
from .serializers import (
    DepartmentSerializer,
    SemesterSerializer,
    CourseSerializer,
    CourseScheduleSerializer,
    EnrollmentSerializer,
)
from .permissions import IsAdminOrInstructor, IsStudent
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter


class BaseViewSet(viewsets.ModelViewSet):
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


 

class SemesterViewSet(BaseViewSet):
    queryset = Semester.objects.all()
    serializer_class = SemesterSerializer
    basename = 'semester'

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]


class CourseViewSet(BaseViewSet):
    queryset = Course.objects.all()
    serializer_class = CourseSerializer
    basename = 'course'
    filter_backends = [DjangoFilterBackend, SearchFilter]
    search_fields = ['code', 'title']
    filterset_fields = ['semester', 'department', 'instructor']
    ordering_fields = ['code', 'title', 'semester', 'created_at']
    ordering = ['code'] 

    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'enrollments']:
            return [permissions.IsAuthenticated()]
        return [IsAdminOrInstructor()]

    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def enrollments(self, request, pk=None):
        course = self.get_object()
        enrollments = Enrollment.objects.filter(course=course)
        serializer = EnrollmentSerializer(enrollments, many=True)
        return Response({
            'success': True,
            'data': serializer.data,
            'message': f'Enrollments for course {course.code} fetched successfully'
        })

 
 