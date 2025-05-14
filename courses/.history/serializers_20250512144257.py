from rest_framework import serializers
from .models import Department, Semester, Course, CourseSchedule, Enrollment
from django.contrib.auth import get_user_model
from departments.serializers import DepartmentSerializer
User = get_user_model()


 


class SemesterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Semester
        fields = '__all__'


class CourseScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseSchedule
        fields = ['id', 'day', 'start_time', 'end_time']


class CourseSerializer(serializers.ModelSerializer):
    department = DepartmentSerializer(read_only=True)
    department_id = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(), source='department', write_only=True
    )

    semester = SemesterSerializer(read_only=True)
    semester_id = serializers.PrimaryKeyRelatedField(
        queryset=Semester.objects.all(), source='semester', write_only=True
    )

    instructor = serializers.StringRelatedField(read_only=True)
    instructor_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role='instructor'), source='instructor', write_only=True
    )

    schedules = CourseScheduleSerializer(many=True, read_only=True)

    class Meta:
        model = Course
        fields = [
            'id', 'code', 'title', 'description', 'credits',
            'instructor', 'instructor_id',
            'department', 'department_id',
            'semester', 'semester_id',
            'prerequisites', 'start_date', 'end_date', 'enrollment_limit',
            'schedules'
        ]


class EnrollmentSerializer(serializers.ModelSerializer):
    student = serializers.HiddenField(default=serializers.CurrentUserDefault())
    
    course = CourseSerializer(read_only=True)
    course_id = serializers.PrimaryKeyRelatedField(
        queryset=Course.objects.all(), source='course', write_only=True
    )

    class Meta:
        model = Enrollment
        fields = ['id', 'student', 'course', 'course_id', 'enrollment_date', 'status', 'final_grade']

