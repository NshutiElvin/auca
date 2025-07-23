from rest_framework import serializers
from .models import UnscheduledExamGroup
from .shared_serializer import CourseGroupSerializer
from .shared_exams_serializers import UnscheduledExamSerializer







class  UnscheduledExamGroupSerializer(serializers.ModelSerializer):

    exam= UnscheduledExamSerializer(read_only=True)
    group= CourseGroupSerializer(read_only=True)

    class Meta:
        model= UnscheduledExamGroup
        fields= ["id", "group", "exam", "created_at", "updated_at"]