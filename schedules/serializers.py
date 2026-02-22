from rest_framework import serializers

from rooms.serializers import LocationSerializer
from semesters.serializers import SemesterSerializer
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
    location=LocationSerializer()
    semester=SemesterSerializer()
  

    class Meta:
        model = MasterTimetable
        fields = [
            "id","academic_year","category", "location", "generated_by", "generated_at", "published_at", "start_date", "end_date", "status", "user", "semester"
,         ]

 


class MasterTimetableExamSerializer(serializers.ModelSerializer):
    master_timetable= MasterTimetableSerializer()
    exam = ExamSerializer()
    
    class Meta:
        model = MasterTimetableExam
        fields = ['id', 'master_timetable', 'exam']
 

