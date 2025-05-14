from django.db import models

# Create your models here.
from django.db import models
from django.utils.translation import gettext_lazy as _
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)   
    updated_at = models.DateTimeField(auto_now=True)       

    class Meta:
        abstract = True 


class Semester(TimeStampedModel):
    name = models.CharField(max_length=50)   
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return self.name
 