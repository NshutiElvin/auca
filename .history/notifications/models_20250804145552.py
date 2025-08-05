from django.db import models

# Create your models here.
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.validators import MaxValueValidator, MinValueValidator

User = get_user_model()

class Notification(models.Model):
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    
    # Notification content
    title = models.CharField(max_length=200)
    message = models.TextField()
  
    
 
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
 
     
    
    def __str__(self):
        return f"{self.get_notification_type_display()} for {self.user}: {self.title}"
    
    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save()
    
    def mark_as_unread(self):
        if self.is_read:
            self.is_read = False
            self.read_at = None
            self.save()