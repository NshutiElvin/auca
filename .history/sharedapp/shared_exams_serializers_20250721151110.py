from rest_framework import serializers
from courses.models import CourseGroup, Course
from courses.serializers import CourseSerializer
from exams.models import UnscheduledExam

class UnscheduledExamSerializer(serializers.ModelSerializer):
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
            "id","course", 
              "course_id", "group_id", "created_at", "updated_at"
        ]
 