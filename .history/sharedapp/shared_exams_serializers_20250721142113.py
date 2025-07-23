from rest_framework import serializers
from .shared_serializer import UnscheduledExamGroupSerializer
from courses.models import CourseGroup, Course
from courses.serializers import CourseSerializer
from exams.models import UnscheduledExam

class UnscheduledExamSerializer(serializers.ModelSerializer):
    group= UnscheduledExamGroupSerializer(read_only=True)
    group_id= serializers.PrimaryKeyRelatedField(
          queryset=CourseGroup.objects.all(), source='group', write_only=True

    )
    course= CourseSerializer(read_only=True)
    course_id= serializers.PrimaryKeyRelatedField(
          queryset=Course.objects.all(), source='course', write_only=True

    )

    class Meta:
        model = UnscheduledExam
        fields = [
            "id", "group", "course", "end_time","date" ,
            "room","status", "course_id", "group_id"
        ]
 