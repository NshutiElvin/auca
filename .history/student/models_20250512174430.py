from django.db import models
from users.models import User
from departments.models import Department
from django.core.exceptions import ValidationError
 

# Create your models here.
class Student(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    reg_no = models.CharField(max_length=20, unique=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True)

    def clean(self):
        if self.user.role != 'student':
            raise ValidationError("Only users with role 'student' can be linked to Student.")
        

