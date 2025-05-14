from rest_framework import serializers
from .models import   Course,  Enrollment
from django.contrib.auth import get_user_model
from courses.serializers import CourseSerializer
from student.models import Student
User = get_user_model()

class CurrentStudentDefault:
    """
    A custom default value class to get the current user's related Student instance.
    """
    requires_context = True

    def __call__(self, serializer_field):
        user = serializer_field.context['request'].user
        try:
            return Student.objects.get(user=user)
        except Student.DoesNotExist:
            raise serializers.ValidationError("Authenticated user is not a student.")
class EnrollmentSerializer(serializers.ModelSerializer):
    student = serializers.HiddenField(default=CurrentStudentDefault())
    
    course = CourseSerializer(read_only=True)
    course_id = serializers.PrimaryKeyRelatedField(
        queryset=Course.objects.all(), source='course', write_only=True
    )

    class Meta:
        model = Enrollment
        fields = ['id', 'student', 'course', 'course_id', 'enrollment_date', 'status', 'final_grade']