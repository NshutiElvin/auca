from rest_framework import serializers
from .models import UnscheduledExamGroup
from .shared_serializer import CourseGroupSerializer
from exams.unscheduled_serializer import UnscheduledExamSerializer







class  UnscheduledExamGroupSerializer(serializers.ModelSerializer):

    course=CourseGroupSerializer(read_only=True)
    exam= UnscheduledExamSerializer(read_only=True)

    class Meta:
        model= UnscheduledExamGroup
        fields= ["id", "course", "exam", "created_at", "updated_at"]