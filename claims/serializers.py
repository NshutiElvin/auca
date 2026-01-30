from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import ClaimResponse, StudentClaim
from student.serializers import StudentSerializer
from users.serializers import UserSerializer
User = get_user_model()



 
 


class StudentClaimSerializer(serializers.ModelSerializer):
    student=StudentSerializer(read_only=True)
    class Meta:
        model = StudentClaim
        fields = ["id","student", "claim_type", "subject", "description", "submitted_at", "status"]


class ClaimResponseSerializer(serializers.ModelSerializer):
    responder =  UserSerializer(read_only=True)
    claim= StudentClaimSerializer(read_only=True)  
    class Meta:
        model = ClaimResponse
        fields = ["id", "claim", "responder", "response_text", "responded_at"]


 




 

