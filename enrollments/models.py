from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from courses.models import Course
from student.models import Student

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)   
    updated_at = models.DateTimeField(auto_now=True)       

    class Meta:
        abstract = True 
class Enrollment(TimeStampedModel):
    STATUS_CHOICES = [
        ('enrolled', 'Enrolled'),
        ('dropped', 'Dropped'),
        ('completed', 'Completed'),
    ]

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='enrollments',
        # limit_choices_to={'role': 'student'}
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrollments')
    enrollment_date = models.DateField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='enrolled')
    final_grade = models.CharField(max_length=2, blank=True, null=True)   

    class Meta:
        unique_together = ('student', 'course')  

    def __str__(self):
        return f"{self.student} in {self.course}"
