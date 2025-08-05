from rest_framework import serializers
from .models import MasterTimetable
from django.contrib.auth import get_user_model
from users.serializers import UserSerializer
User = get_user_model()
 
class MaterTimetableSerializer(serializers.ModelSerializer):
    user= UserSerializer(read_only=True) 
 

    class Meta:
        model = MasterTimetable
        fields = [
            "id","academic_year", "generated_by", "generated_at", "published_at", "start_date", "end_date", "status", "user"
         ]

 

