from django.db import models
from import_export import resources
# Create your models here.
class RawEnrollments(models.Model):
    COURSECODE= models.CharField(max_length=100)
    COURSENAME= models.CharField(max_length=250)
    CREDITS= models.IntegerField()
    GROUP= models.CharField(max_length=100)
    STUDNUM= models.IntegerField()
    STUDNAME= models.CharField(max_length=250)
    FACULITYCODE= models.CharField(max_length=100)
    TERM= models.CharField(max_length=100)
   
class RawEnrollmentsResource(resources.ModelResource):

    class Meta:
        model = RawEnrollments
        import_id_fields = ["STUDNUM"]
        skip_unchanged = True
        use_bulk = True