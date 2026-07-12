from django.db import models, transaction

# Create your models here.
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
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Nothing enforced "at most one active semester" before this, and
        # several places do Semester.objects.get(is_active=True) — with 2+
        # active semesters that raises MultipleObjectsReturned (a 500) with
        # no clear cause in the response.
        if self.is_active:
            with transaction.atomic():
                Semester.objects.exclude(pk=self.pk).update(is_active=False)
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)
