from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Notification
from .serializers import NotificationSerializer, MarkAsReadSerializer
from django.utils import timezone

class NotificationViewSet(viewsets.ModelViewSet):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user).order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=['post'])
    def mark_as_read(self, request, pk=None):
        notification = self.get_object()
        serializer = MarkAsReadSerializer(data=request.data)
        
        if serializer.is_valid():
            is_read = serializer.validated_data['is_read']
            
            if is_read:
                notification.mark_as_read()
            else:
                notification.mark_as_unread()
            
            return Response({'status': 'marked as read' if is_read else 'marked as unread'})
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def unread(self, request):
        unread_notifications = self.get_queryset().filter(is_read=False)
        serializer = self.get_serializer(unread_notifications, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def mark_all_as_read(self, request):
        updated = self.get_queryset().filter(is_read=False).update(
            is_read=True,
            read_at=timezone.now()
        )
        return Response({'status': f'{updated} notifications marked as read'})
    


