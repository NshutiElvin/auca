from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .serializers import ConfigSerializer
from .utils import JsonConfigManager


class ConfigViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet
):
    """
    ViewSet for configuration management
    """
    serializer_class = ConfigSerializer
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config_manager = JsonConfigManager()
    
    def list(self, request, *args, **kwargs):
        """Get current configuration"""
        try:
            config_data = self.config_manager.read_config()
            return Response(config_data)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def create(self, request, *args, **kwargs):
        """Replace entire configuration"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            new_config = serializer.validated_data['config']
            self.config_manager.write_config(new_config)
            return Response(
                serializer.validated_data,
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def retrieve(self, request, *args, **kwargs):
        """Get specific config section (if needed)"""
        # You can implement logic to get specific parts of config
        return self.list(request, *args, **kwargs)
    
    @action(detail=False, methods=['patch'])
    def partial(self, request):
        """Partial update endpoint"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            updates = serializer.validated_data['config']
            updated_config = self.config_manager.update_config(updates)
            return Response(updated_config)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )