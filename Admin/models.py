from django.db import models
from users.models import User
from departments.models import Department
from django.core.exceptions import ValidationError
 

# Create your models here.
class Admin(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    def clean(self):
        if self.user.role != 'admin':
            raise ValidationError("Only users with role 'admin' can be linked to Admin.")
        

