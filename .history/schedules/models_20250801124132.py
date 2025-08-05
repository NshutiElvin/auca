from django.db import models
from courses.models import Course
from django.contrib.auth import get_user_model

User= get_user_model()
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)   
    updated_at = models.DateTimeField(auto_now=True)       

    class Meta:
        abstract = True 
# Create your models here.
class MasterTimetable( TimeStampedModel):
    STATUS_CHOICES = [
        ('DRAFT', 'draft'),
        ('PUBLISHED', 'published'),
        ('ARCHIEVED', 'archieved'),
    ]

    academic_year= models.CharField(max_length=255, null=False)
    generated_by= models.ForeignKey(User, on_delete=models.CASCADE, null=False)
    generated_at=models.DateTimeField(auto_now_add=True)
    published_at= models.DateTimeField(auto_now=True)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='SCHEDULED')

    def __str__(self):
        return f"{self.academic_year} - {self.generated_at}"
    

    


