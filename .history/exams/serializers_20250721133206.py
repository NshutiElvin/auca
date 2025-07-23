from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import  Exam, StudentExam
from sharedapp.shared_serializer import CourseGroupSerializer
from courses.models import  CourseGroup, Course
from rooms.serializers import RoomSerializer
from rooms.models import Room

from student.models import Student
from student.serializers import StudentSerializer


User = get_user_model()
class ExamSerializer(serializers.ModelSerializer):
    group= CourseGroupSerializer(read_only=True)
    group_id= serializers.PrimaryKeyRelatedField(
          queryset=CourseGroup.objects.all(), source='group', write_only=True

    )
    room=RoomSerializer(read_only=True)
    room_id= serializers.PrimaryKeyRelatedField(
          queryset=Room.objects.all(), source='room', write_only=True

    )

    class Meta:
        model = Exam
        fields = [
            "id", "group", "start_time", "end_time","date" ,
            "room","status", "room_id", "group_id"
        ]

class StudentExamSerializer(serializers.ModelSerializer):
    student= StudentSerializer(read_only=True)

    student_id= serializers.PrimaryKeyRelatedField(
          queryset=Student.objects.all(), source='student', write_only=True

    )
    room=RoomSerializer(read_only=True)
    room_id= serializers.PrimaryKeyRelatedField(
          queryset=Room.objects.all(), source='room', write_only=True

    )
    exam=ExamSerializer(read_only=True)
    exam_id= serializers.PrimaryKeyRelatedField(
          queryset=Exam.objects.all(), source='exam', write_only=True

    )
    class Meta:
        model = StudentExam
        fields = (
            "id", "student", "student_id", "exam","exam_id" ,
            "room","status", "room_id"
        )



