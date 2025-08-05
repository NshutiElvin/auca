from django.db import models
from courses.models import Course
from courses.models import Course
from django.contrib.auth import get_user_model
from exams.models import MasterTimetableExam

User= get_user_model()
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)   
    updated_at = models.DateTimeField(auto_now=True)       

    class Meta:
        abstract = True 
# Create your models here.
class CourseSchedule( TimeStampedModel):
    DAYS_OF_WEEK = [
        ('MON', 'Monday'),
        ('TUE', 'Tuesday'),
        ('WED', 'Wednesday'),
        ('THU', 'Thursday'),
        ('FRI', 'Friday'),
        ('SAT', 'Saturday'),
        ('SUN', 'Sunday'),
    ]

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='schedules')
    day = models.CharField(max_length=3, choices=DAYS_OF_WEEK)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        unique_together = ('course', 'day', 'start_time')

    def __str__(self):
        return f"{self.course.code} - {self.get_day_display()} {self.start_time}-{self.end_time}"
    




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
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='DRAFT')
    exams = models.ManyToManyField('Exam', through=MasterTimetableExam, related_name='timetables')

    def __str__(self):
        return f"{self.academic_year} - {self.generated_at}"
    






    


