from datetime import time as time_cls
from django.conf import settings
from django.db import models
class Location(models.Model):
    name = models.CharField(max_length=50, unique=True)
 
    def __str__(self):
        return f"{self.name}"
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)   
    updated_at = models.DateTimeField(auto_now=True)       

    class Meta:
        abstract = True 

 
class Room(TimeStampedModel):
    name = models.CharField(max_length=50, unique=True)
    capacity = models.PositiveIntegerField()
    location= models.ForeignKey(Location, null=True, blank=True, on_delete=models.SET_NULL )
    rows = models.PositiveIntegerField(null=True, blank=True)
    columns = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.capacity} seats)"

    def has_seat_layout(self):
        return bool(self.rows and self.columns)
    




class RoomAllocationSwitch(models.Model):
    is_enabled = models.BooleanField(default=True)

    def __str__(self):
        return "Enabled" if self.is_enabled else "Disabled"


class RoomOutOfService(TimeStampedModel):
    """
    A maintenance/blocked window for a room, hotel-style: the room is
    unavailable for scheduling on every date in [start_date, end_date],
    during the [start_time, end_time) portion of each of those days.
    Defaults to the full day, covering the common "room closed all day for
    N days" case without requiring the admin to think about times.
    """
    room = models.ForeignKey(
        Room, on_delete=models.CASCADE, related_name="out_of_service_periods"
    )
    start_date = models.DateField()
    end_date = models.DateField()
    start_time = models.TimeField(default=time_cls.min)
    end_time = models.TimeField(default=time_cls.max)
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.room.name} out of service {self.start_date}–{self.end_date}"

    def blocks(self, date, start_time, end_time):
        """Does this block cover the given (date, start_time, end_time) exam slot?"""
        return (
            self.start_date <= date <= self.end_date
            and self.start_time < end_time
            and start_time < self.end_time
        )