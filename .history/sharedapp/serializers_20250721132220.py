from rest_framework import serializers
from exams.serializers import UnscheduledExamSerializer
from .models import UnscheduledExamGroup
from .shared_serializer import CourseGroupSerializer







class  UnscheduledExamGroupSerializer(serializers.ModelSerializer):

    course=CourseGroupSerializer(read_only=True)
    exam= UnscheduledExamSerializer(read_only=True)

    class Meta:
        model= UnscheduledExamGroup
        fields= ["id", "course", "exam", "created_at", "updated_at"]