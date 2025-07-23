from rest_framework import serializers
from .models import CourseSchedule 
from django.contrib.auth import get_user_model
User = get_user_model()


 

 


class CourseScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseSchedule
        fields = ['id', 'day', 'start_time', 'end_time']

 

 

