from rest_framework import serializers
from .models import  Semester
from django.contrib.auth import get_user_model
User = get_user_model()


 


class SemesterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Semester
        fields = '__all__'


 