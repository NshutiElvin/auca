from rest_framework import serializers
from .models import   Course,  Enrollment
from django.contrib.auth import get_user_model
from courses.serializers import CourseSerializer
from courses.models import CourseGroup
from sharedapp.shared_serializer import CourseGroupSerializer
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
    group = CourseGroupSerializer(read_only=True)
    group_id = serializers.PrimaryKeyRelatedField(
        queryset=CourseGroup.objects.all(), source='group',
        write_only=True, required=False, allow_null=True,
    )

    class Meta:
        model = Enrollment
        fields = ['id', 'student', 'course', 'course_id', 'enrollment_date', 'status', 'final_grade', 'amount_paid', 'amount_to_pay', 'group', 'group_id']

    def get_fields(self):
        # amount_paid / amount_to_pay / final_grade / status are financial
        # and academic records — only an admin or instructor may set them.
        # Without this, any authenticated student could self-report their
        # enrollment as fully paid or grade themselves, since these fields
        # were otherwise plain writable model fields with no restriction.
        fields = super().get_fields()
        request = self.context.get('request')
        is_staff_caller = bool(
            request and request.user and request.user.is_authenticated
            and getattr(request.user, 'role', None) in ('admin', 'instructor')
        )
        if not is_staff_caller:
            for field_name in ('amount_paid', 'amount_to_pay', 'final_grade', 'status'):
                fields[field_name].read_only = True
        return fields