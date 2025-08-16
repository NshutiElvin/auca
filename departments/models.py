from django.db import models
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)   
    updated_at = models.DateTimeField(auto_now=True)       

    class Meta:
        abstract = True 
class Department(TimeStampedModel):
    code = models.CharField(max_length=10, unique=True)  
    name = models.CharField(max_length=100)
    location= models.ForeignKey("rooms.Location", null=True, blank=True, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.code} - {self.name}"