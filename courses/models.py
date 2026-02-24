from django.db import models
from django.conf import settings
from departments.models import Department
from django.utils.translation import gettext_lazy as _
from semesters.models import Semester

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)   
    updated_at = models.DateTimeField(auto_now=True)       

    class Meta:
        abstract = True 


 
class Course(TimeStampedModel):
   
    code = models.CharField(max_length=10, unique=True)
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    credits = models.PositiveIntegerField(default=3)

    

    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='courses')
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE, related_name='courses')
    is_cross_departmental = models.BooleanField(default=False)
    associated_departments= models.ManyToManyField(Department, blank=True, related_name='associated_courses')
    prerequisites = models.ManyToManyField('self', blank=True, symmetrical=True, null=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    enrollment_limit = models.PositiveIntegerField(default=30, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']
        indexes = [
            models.Index(fields=['semester', 'department']),
            models.Index(fields=['code']),
            models.Index(fields=['created_at']),
        ]
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.title}"
    
    @property
    def all_departments(self):
        """Returns all departments associated with this course"""
        depts = [self.department]
        if self.is_cross_departmental:
            depts.extend(self.associated_departments.all())
        return depts
    

class CourseGroup(models.Model):

    course= models.ForeignKey(Course, on_delete=models.CASCADE, null=False, blank=False)
    max_member= models.IntegerField(default=0)
    group_name= models.CharField(max_length=255, null=False, blank=False)
    current_member= models.IntegerField(default=0)
    start_time = models.TimeField( null=True, blank=True)
    end_time = models.TimeField( null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='courses_taught',
        limit_choices_to={'role': 'instructor'}
    )

    class Meta:
        ordering = ['group_name']

    def __str__(self):
        return f"{self.course} - {self.group_name}"

