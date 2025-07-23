from rest_framework import serializers
from .models import CourseSchedule, UnscheduledExam
from django.contrib.auth import get_user_model
from courses.serializers import  UnscheduledExamGroupSerializer, CourseSerializer
from courses.models import CourseGroup, Course
User = get_user_model()


 

 


class CourseScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseSchedule
        fields = ['id', 'day', 'start_time', 'end_time']

 

