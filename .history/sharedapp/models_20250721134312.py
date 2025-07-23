from django.db import models
from courses.models import CourseGroup

# Create your models here.
class UnscheduledExamGroup(models.Model):
        exam= models.ForeignKey("exams.UnscheduledExam", on_delete=models.CASCADE)
        group=models.ForeignKey(CourseGroup, on_delete=models.CASCADE)
        created_at = models.DateTimeField(auto_now_add=True)   
        updated_at = models.DateTimeField(auto_now=True)       