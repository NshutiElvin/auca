from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from .models import  CourseSchedule
from .serializers import (
    CourseScheduleSerializer,
)
from .permissions import IsAdminOrInstructor
from rest_framework.decorators import action
from .utils import get_exam_slots
import json
import datetime
from django.utils.dateparse import parse_date
 
 

 
class CourseScheduleViewSet(viewsets.ModelViewSet):
    queryset = CourseSchedule.objects.all()
    serializer_class = CourseScheduleSerializer
    basename = 'schedule'

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
        return [IsAdminOrInstructor()]

    @action(detail=False, methods=['get'], url_path='slots')
    def generate_slots(self, request, *args, **kwargs):
        try:

            date="2025-07-17T22:00:00.000Z"
            if date and "T" in date:
                date = date.split("T")[0] 

           

            end_date="2025-07-30T22:00:00.000Z"
            if end_date and "T" in end_date:
                end_date = end_date.split("T")[0] 

            date = parse_date("2025-07-17") 
            end_date = parse_date("2025-07-30") 

            slots=get_exam_slots(date,end_date, max_slots=40)
            return Response({
            "success": True,
            "data": slots,
            "message": "Fetched successfully"
        })

        except Exception as e:
             return Response({
            "success": True,
            "data": str(e),
            "message": "Fetched successfully"
        })



 