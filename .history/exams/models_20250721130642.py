from django.db import models
from rooms.models import Room
from  student.models import Student
from datetime import datetime

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)   
    updated_at = models.DateTimeField(auto_now=True)       

    class Meta:
        abstract = True 
class Exam(TimeStampedModel):
    STATUS_CHOICES = [
        ('SCHEDULED', 'Scheduled'),
        ('ONGOING', 'Ongoing'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='SCHEDULED')
    group= models.ForeignKey("courses.CourseGroup", on_delete=models.DO_NOTHING, null=True)

     
    def __str__(self):
        return f"{self.group.course.code} - {self.date} - {self.status}"

    def update_status(self):
        now = datetime.now()
        exam_datetime = datetime.combine(self.date, self.start_time)
        exam_end_datetime = datetime.combine(self.date, self.end_time)

        if self.status != 'CANCELLED':
            if now < exam_datetime:
                self.status = 'SCHEDULED'
            elif exam_datetime <= now <= exam_end_datetime:
                self.status = 'ONGOING'
            elif now > exam_end_datetime:
                self.status = 'COMPLETED'
            self.save(update_fields=['status'])
    
class StudentExam(TimeStampedModel):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('COMPLETED', 'Completed'),
        ('MISSED', 'Missed'),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')

    def __str__(self):
        return f"{self.student.reg_no} - {self.exam.group.course.code} - {self.status}"
class UnscheduledExam(models.Model):

    course= models.ForeignKey("courses.Course", on_delete=models.CASCADE, related_name="unscheduled_exam")
    groups= models.ManyToManyField("courses.UnscheduledExamGroup" )
    created_at = models.DateTimeField(auto_now_add=True)   
    updated_at = models.DateTimeField(auto_now=True)       
