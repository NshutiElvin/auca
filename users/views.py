from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model
from .serializers import UserSerializer, CustomTokenObtainPairSerializer, PasswordChangeSerializer
from .permissions import IsAdmin, IsModerator
from .validators import get_password_strength
from rest_framework.permissions import AllowAny
from django.contrib.auth.models import Permission
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
User = get_user_model()
import pprint
class CustomTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        
        refresh_token = request.COOKIES.get('refresh_token')
        if refresh_token is None:
            return Response({"detail": "Refresh token not found in cookies."}, status=status.HTTP_401_UNAUTHORIZED)
         
        request.data['refresh'] = refresh_token
        return super().post(request, *args, **kwargs)

class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            refresh_token = response.data.get('refresh')
            response.set_cookie(
                key='refresh_token',
                value=refresh_token,
                httponly=True,
                secure=True,  
                samesite='None',  
                max_age=60*60*24   
            )
            response.data.pop('refresh', None)
        return response

 
class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    def get_queryset(self):
        # Optimize queries by prefetching permissions
        queryset = User.objects.prefetch_related('user_permissions')
        return queryset
        
    def get_permissions(self):
        if self.action == "logout":
            permission_classes = [permissions.IsAuthenticated]
        elif self.action == 'create':
            permission_classes = [permissions.AllowAny]
        elif self.action in ['list', 'retrieve']:
            permission_classes = [permissions.IsAuthenticated]
        elif self.action in ['check_password_strength']:
            permission_classes = [permissions.AllowAny]
        elif self.action in ['change_password']:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [IsAdmin]
        return [permission() for permission in permission_classes]
    
    def create(self, request, *args, **kwargs):
        data=request.data
        data.pop("permissions", None)
        pprint.pprint(data)
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response({
            'success': True,
            'data': serializer.data,
            'message': 'User created successfully'
        }, status=status.HTTP_201_CREATED, headers=headers)
    
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'success': True,
            'data': serializer.data,
            'message': 'Users fetched successfully'
        })
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({
            'success': True,
            'data': serializer.data,
            'message': 'User fetched successfully'
        })
    
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        data=request.data
        pprint.pprint(data)
        data.pop("permissions", None)
        serializer = self.get_serializer(instance, data=data, partial=partial)
       
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response({
            'success': True,
            'data': serializer.data,
            'message': 'User updated successfully'
        })
    
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response({
            'success': True,
            'message': 'User deleted successfully'
        }, status=status.HTTP_204_NO_CONTENT)
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def profile(self, request):
        serializer = self.get_serializer(request.user)
        return Response({
            'success': True,
            'data': serializer.data,
            'message': 'Profile fetched successfully'
        })
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def user_permissions(self, request):
        user_permissionss= Permission.objects.all()
        known_models= [
        "course",
        "department",
        "enrollment",
        "student",
        "exam",
        "studentexam",
        "unscheduledexam", 
        "room",
        
    ]
        data = [ ]
          
        for perm in user_permissionss:
            if perm.content_type.model in known_models:
                data.append(  {
                "codename": perm.codename,
                "name": perm.name,
                "model": perm.content_type.model
            })
        return Response({
            'success': True,
            'data': data,
            'message': 'Profile fetched successfully'
        })
    
    @action(detail=False, methods=['post'], permission_classes=[permissions.AllowAny])
    def check_password_strength(self, request):
        """
        Check the strength of a password without saving it
        """
        password = request.data.get('password')
        if not password:
            return Response({
                'success': False,
                'message': 'Password is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        user = None
        if request.user.is_authenticated:
            user = request.user
            
        strength_info = get_password_strength(password, user)
        
        return Response({
            'success': True,
            'data': strength_info,
            'message': 'Password strength checked successfully'
        })
    
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def change_password(self, request):
        """
        Change user password
        """
        serializer = PasswordChangeSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        return Response({
            'success': True,
            'data': {'password_strength': serializer.data.get('password_strength')},
            'message': 'Password changed successfully'
        })
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def instructors(self, request):
        Instructors = User.objects.filter(role='instructor')
        serializer = self.get_serializer(Instructors, many=True)

        
        return Response({
            'success': True,
            'data': serializer.data,
            'message': 'Instructors fetched successfully'
        })
    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def logout(self, request):
        try:
            response = Response({'success': True, 'message': 'Logged out successfully'})
            
            refresh_token = request.COOKIES.get('refresh_token')
            if refresh_token:
                try:
                    token = RefreshToken(refresh_token)
                    token.blacklist()
                except Exception as e:
                    print(f"Error blacklisting refresh token: {str(e)}")
                
                response.delete_cookie('refresh_token')
            
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                access_token_str = auth_header.split(' ')[1]
                try:
                    outstanding_token = OutstandingToken.objects.get(token=access_token_str)
                    BlacklistedToken.objects.get_or_create(token=outstanding_token)
                except OutstandingToken.DoesNotExist:
                    pass
                except Exception as e:
                    print(f"Error blacklisting access token: {str(e)}")
            
            return response

        except Exception as e:
            return Response({'success': False, 'message': str(e)}, status=400)
            
        














