from rest_framework import viewsets, status, permissions
from rest_framework.response import Response

from .models import ClaimResponse, StudentClaim
from .serializers import StudentClaimSerializer, ClaimResponseSerializer
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from student.models import Student
from rest_framework.exceptions import PermissionDenied


class BaseViewSet(viewsets.ModelViewSet):
    """
    Base ViewSet to format responses consistently
    """
    filter_backends = [DjangoFilterBackend, SearchFilter]

    def _resource_name(self):
        try:
            return getattr(self, "basename")
        except Exception:
            return self.get_queryset().model.__name__.lower()

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            data = serializer.data
            return self.get_paginated_response({"success": True, "data": data})

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "success": True,
            "data": serializer.data,
            "message": f"{self._resource_name().title()}s fetched successfully"
        })

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if not user.is_staff:
            try:
                student = Student.objects.get(user=user)
                # Students only see their own claims
                queryset = queryset.filter(student=student)
            except Student.DoesNotExist:
                queryset = StudentClaim.objects.none()

        return queryset

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({
            "success": True,
            "data": serializer.data,
            "message": f"{self._resource_name().title()} fetched successfully"
        })

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response({
            "success": True,
            "data": serializer.data,
            "message": f"{self._resource_name().title()} created successfully"
        }, status=status.HTTP_201_CREATED, headers=headers)
    
    def perform_create(self, serializer):
        try:
            student_instance = Student.objects.get(user=self.request.user)
            serializer.save(student=student_instance)
        except Student.DoesNotExist:
            raise PermissionDenied("No student record found for this user.")

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response({
            "success": True,
            "data": serializer.data,
            "message": f"{self._resource_name().title()} updated successfully"
        })

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response({
            "success": True,
            "message": f"{self._resource_name().title()} deleted successfully"
        }, status=status.HTTP_204_NO_CONTENT)


class StudentClaimViewSet(BaseViewSet):
    queryset = StudentClaim.objects.all()
    serializer_class = StudentClaimSerializer
    basename = "student claim"
    filter_backends = [DjangoFilterBackend, SearchFilter]
    search_fields = ["claim_type", "description", "subject"]
    filterset_fields = ["status", "student"]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.IsAuthenticated()]
        if self.action in ["create"]:
            return [permissions.IsAuthenticated()]
        # restrict modifications to admin users
        return [permissions.IsAdminUser()]

    def perform_create(self, serializer):
        # automatically set student to request.user if model has student FK
        try:
            student_instance = Student.objects.get(user=self.request.user)
            serializer.save(student=student_instance)
        except Student.DoesNotExist:
            # fallback if no Student record exists for this user
            serializer.save()
        except TypeError:
            serializer.save()

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def add_response(self, request, pk=None):
        """
        Add a ClaimResponse to this StudentClaim.
        """
        claim = self.get_object()
        
        # Don't modify request.data - pass response_text directly to serializer
        serializer = ClaimResponseSerializer(data={
            'response_text': request.data.get('message', '')
        })
        serializer.is_valid(raise_exception=True)
        
        # Pass both claim and responder to save()
        serializer.save(claim=claim, responder=request.user)
        
        return Response({
            "success": True,
            "data": serializer.data,
            "message": "Response added to claim successfully"
        }, status=status.HTTP_201_CREATED)


class ClaimResponseViewSet(BaseViewSet):
    queryset = ClaimResponse.objects.all()
    serializer_class = ClaimResponseSerializer
    basename = "claim response"
    filter_backends = [DjangoFilterBackend, SearchFilter]
    search_fields = ["response_text"]  # Changed from "message" to "response_text"
    filterset_fields = ["claim", "responder"]

    def get_queryset(self):
        """
        Filter queryset based on user permissions and query parameters.
        """
        queryset = super().get_queryset()
        user = self.request.user
        
        # Get claim_id from query parameters for filtering
        claim_id = self.request.query_params.get('claim')
        print("Filtering by claim_id for admin:", claim_id)
        
        if not user.is_staff:
            try:
                student = Student.objects.get(user=user)
                # Filter through claim -> student relationship
                queryset = queryset.filter(claim__student=student)  # <-- fix here
                
                if claim_id:
                    try:
                        claim = StudentClaim.objects.get(id=claim_id, student=student)
                        queryset = queryset.filter(claim=claim)
                    except StudentClaim.DoesNotExist:
                        queryset = ClaimResponse.objects.none()
            except Student.DoesNotExist:
                queryset = ClaimResponse.objects.none()
                return queryset

    def get_permissions(self):
        """
        Set permissions based on action.
        - All authenticated users can list and retrieve responses
        - Only admins can create, update, or delete responses directly
        """
        if self.action in ["list", "retrieve"]:
            return [permissions.IsAuthenticated()]
        
        # For create, update, delete actions - only admins
        return [permissions.IsAdminUser()]

    def perform_create(self, serializer):
        """
        Automatically set the responder when creating a response.
        """
        serializer.save(responder=self.request.user)

    @action(detail=False, methods=['get'])
    def by_claim(self, request):
        """
        Custom action to get responses for a specific claim.
        Example: GET /api/claims/responses/by_claim/?claim=1
        """
        claim_id = request.query_params.get('claim')
        if not claim_id:
            return Response({
                "success": False,
                "message": "claim parameter is required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            claim_id = int(claim_id)
            claim = StudentClaim.objects.get(id=claim_id)
            
            # Check permissions
            user = request.user
            if not user.is_staff:
                try:
                    student = Student.objects.get(user=user)
                    if claim.student != student:
                        return Response({
                            "success": False,
                            "message": "You can only view responses for your own claims"
                        }, status=status.HTTP_403_FORBIDDEN)
                except Student.DoesNotExist:
                    return Response({
                        "success": False,
                        "message": "Student record not found"
                    }, status=status.HTTP_403_FORBIDDEN)
            
            # Get responses for this claim
            responses = self.get_queryset().filter(claim=claim)
            serializer = self.get_serializer(responses, many=True)
            
            return Response({
                "success": True,
                "data": serializer.data,
                "message": f"Responses for claim #{claim_id} fetched successfully"
            })
            
        except (ValueError, TypeError):
            return Response({
                "success": False,
                "message": "Invalid claim ID format"
            }, status=status.HTTP_400_BAD_REQUEST)
        except StudentClaim.DoesNotExist:
            return Response({
                "success": False,
                "message": f"Claim with id {claim_id} not found"
            }, status=status.HTTP_404_NOT_FOUND)