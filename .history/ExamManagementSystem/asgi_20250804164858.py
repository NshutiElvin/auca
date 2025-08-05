import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ai_recruitment_system.settings")
django.setup() 
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import notifications.routing
import notifications.routing
from .channnel_auth_middleware import JwtAuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator


 
 
application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket":  JwtAuthMiddlewareStack(
        URLRouter(
            notifications.routing.websocket_urlpatterns
        )
    ),
})


list=[i for i in range(10)]
def my_filter(x):
    return x%2==0
filtered_list= filter()