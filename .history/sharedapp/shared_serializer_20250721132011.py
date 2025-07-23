from courses.serializers import CourseSerializer
from rest_framework import serializers
from courses.models import UnscheduledExamGroup
class CourseGroupSerializer(serializers.ModelSerializer):
    course= CourseSerializer(read_only=True)


    class Meta:
        model = UnscheduledExamGroup
        fields = ["id", "course", "max_member", "group_name", "current_member", "created_at", "updated_at"]