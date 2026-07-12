from django.db import models
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)   
    updated_at = models.DateTimeField(auto_now=True)       

    class Meta:
        abstract = True 
class Department(TimeStampedModel):
    code = models.CharField(max_length=255, unique=True)  
    name = models.CharField(max_length=100)
    # SET_NULL, not CASCADE: the field is optional (null=True), so deleting a
    # Location must not cascade-delete every Department (and therefore every
    # Course -> Enrollment, both CASCADE) that happened to reference it.
    location= models.ForeignKey("rooms.Location", null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return f"{self.code} - {self.name}"