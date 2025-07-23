from django.db import models
from courses.models import Course
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)   
    updated_at = models.DateTimeField(auto_now=True)       

    class Meta:
        abstract = True 
# Create your models here.
 
    

    
    class UnscheduledExam(models.Model):

        course= models.ForeignKey(Course, on_delete=models.CASCADE, related_name="unscheduled_exam")
        groups= models.ManyToManyField("courses.UnscheduledExamGroup" )
        created_at = models.DateTimeField(auto_now_add=True)   
        updated_at = models.DateTimeField(auto_now=True)       

