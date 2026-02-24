from rest_framework import serializers
from .models import CourseGroup, Department, Semester, Course
from django.contrib.auth import get_user_model
from departments.serializers import DepartmentSerializer
from schedules.models import CourseSchedule
from semesters.serializers import SemesterSerializer
from users.serializers import UserSerializer
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
    associated_departments = DepartmentSerializer(many=True, read_only=True)
    associated_department_ids = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(),
        source='associated_departments',
        many=True,
        write_only=True,
        required=False,
        allow_empty=True
    )
    
    schedules = CourseScheduleSerializer(many=True, read_only=True)
    students_enrolled = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = [
            'id', 'code', 'title', 'description', 'credits',
            'department', 'department_id',
            'semester', 'semester_id',
            'prerequisites', 'start_date', 'end_date', 'enrollment_limit',
            'schedules',  'students_enrolled',
            'is_cross_departmental',
            'associated_departments', 'associated_department_ids',
        ]
    def get_students_enrolled(self, obj):
        return obj.enrollments.filter(status='active').count()
     
    
class CourseGroupSerializer(serializers.ModelSerializer):
    course = CourseSerializer(read_only=True)
    course_id = serializers.PrimaryKeyRelatedField(
        queryset=Course.objects.all(), source='course', write_only=True
    )
    instructor = UserSerializer(read_only=True)
    instructor_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role='instructor'), source='instructor', write_only=True
    )

    class Meta:
        model = CourseGroup
        fields = ['id', 'course', 'course_id', 'group_name','instructor', 'instructor_id', 'max_member', 'current_member', 'start_time', 'end_time']





 

