from django.db import models

from student.models import Student
from django.conf import settings


# Create your models here.
class StudentClaim(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    claim_type = models.CharField(max_length=100)
    subject = models.CharField(max_length=255)
    description = models.TextField()
    submitted_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=50, default='pending')

    def __str__(self):
        return f"Claim {self.id} by Student {self.student.reg_no}"
    
class ClaimResponse(models.Model):
    claim = models.ForeignKey(StudentClaim, on_delete=models.CASCADE, related_name='responses')
    responder= models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    response_text = models.TextField()
    responded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Response {self.id} to Claim {self.claim.id}"