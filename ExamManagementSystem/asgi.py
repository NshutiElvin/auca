import os
import django
# Was "ai_recruitment_system.settings" — an unrelated project's settings
# module that doesn't exist in this repo. django.setup() below would raise
# ModuleNotFoundError the moment anything loaded this ASGI app (daphne/
# uvicorn, or Channels' dev-server integration), meaning the entire
# WebSocket layer (real-time notifications + exam data) could never
# actually start, unless something else already exported
# DJANGO_SETTINGS_MODULE before Python started (nothing in this repo does).
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ExamManagementSystem.settings")
django.setup()
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
import notifications.routing
from .channnel_auth_middleware import JwtAuthMiddlewareStack

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket":  JwtAuthMiddlewareStack(
        URLRouter(
            notifications.routing.websocket_urlpatterns
        )
    ),
})


