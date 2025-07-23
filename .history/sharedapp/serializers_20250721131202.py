from rest_framework import serializers
from courses.serializers import CourseGroupSerializer
from exams.serializers import UnscheduledExamSerializer
from courses.models import UnscheduledExamGroup


class  UnscheduledExamGroupSerializer(serializers.ModelSerializer):

    course=CourseGroupSerializer(read_only=True)
    exam= UnscheduledExamSerializer(read_only=True)

    class Meta:
        model= UnscheduledExamGroup
        fields= ["id", "course", "exam", "created_at", "updated_at"]