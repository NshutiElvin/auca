from django.db import models
from django.conf import settings
from departments.models import Department
from django.utils.translation import gettext_lazy as _
from semesters.models import Semester
from django.contrib.auth import get_user_model

User= get_user_model()

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)   
    updated_at = models.DateTimeField(auto_now=True)       

    class Meta:
        abstract = True 


 
class Course(TimeStampedModel):
    GROUP_CHOICES = [
        ('A', 'Group A'),
        ('B', 'Group B'),
        ('C', 'Group C'),
        ('D', 'Group D'),
        ('E', 'Group E'),
        ('F', 'Group F'),
        
    ]
    code = models.CharField(max_length=10, unique=True)
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    credits = models.PositiveIntegerField(default=3)

    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='courses_taught',
        limit_choices_to={'role': 'instructor'}
    )

    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='courses')
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE, related_name='courses')

    prerequisites = models.ManyToManyField('self', blank=True, symmetrical=False)
    start_date = models.DateField()
    end_date = models.DateField()
    enrollment_limit = models.PositiveIntegerField(default=30)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.title}"
    

class CourseGroup(models.Model):

    course= models.ForeignKey(Course, on_delete=models.CASCADE, null=False, blank=False)
    max_member= models.IntegerField(default=0)
    group_name= models.CharField(max_length=255, null=False, blank=False)
    current_member= models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['group_name']

    def __str__(self):
        return f"{self.course} - {self.group_name}"
class UnscheduledExamGroup(models.Model):
        unscheduledExam= models.ForeignKey("schedules.UnscheduledExam", on_delete=models.CASCADE)
        group=models.ForeignKey(CourseGroup, on_delete=models.CASCADE)