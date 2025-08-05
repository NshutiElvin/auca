from rest_framework import serializers
from .models import CourseSchedule
from rest_framework import serializers
from .models import MasterTimetable, MasterTimetableExam
from django.contrib.auth import get_user_model
from users.serializers import UserSerializer
from exams.serializers import ExamSerializer

User = get_user_model()
User = get_user_model()


 

 
class CourseScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseSchedule
        fields = ['id', 'day', 'start_time', 'end_time']




 
class MasterTimetableSerializer(serializers.ModelSerializer):
    user= UserSerializer(read_only=True) 
    generated_by=  UserSerializer()   
  

    class Meta:
        model = MasterTimetable
        fields = [
            "id","academic_year", "generated_by", "generated_at", "published_at", "start_date", "end_date", "status", "user"
         ]

 


class MasterTimetableExamSerializer(serializers.ModelSerializer):
    exam = ExamSerializer()
    
    class Meta:
        model = MasterTimetableExam
        fields = ['id', 'master_timetable', 'exam']
 

