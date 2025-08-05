"""General web socket middlewares
"""

from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.authentication import JWTTokenUserAuthentication
from django.contrib.auth.models import User
from channels.middleware import BaseMiddleware
from channels.auth import AuthMiddlewareStack
from django.db import close_old_connections
from urllib.parse import parse_qs
from jwt import decode as jwt_decode
from django.conf import settings


@database_sync_to_async
def get_user(validated_token):
    try:
        user = get_user_model().objects.get(id=validated_token["user_id"])
        # return get_user_model().objects.get(id=toke_id)
        print(f"{user}")
        return user
   
    except User.DoesNotExist:
        return AnonymousUser()



class JwtAuthMiddleware(BaseMiddleware):
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
       # Close old database connections to prevent usage of timed out connections
        close_old_connections()

        # Get the token
        token = parse_qs(scope["query_string"].decode("utf8"))["token"][0]

        # Try to authenticate the user
        try:
            # This will automatically validate the token and raise an error if token is invalid
            UntypedToken(token)
        except (InvalidToken, TokenError) as e:
            # Token is invalid
            print(e)
            scope["user"] = AnonymousUser()
        else:
            #  Then token is valid, decode it
            decoded_data = jwt_decode(token, settings.JWT_SIGNING_KEY, algorithms=["HS256"])
            scope["user"] = await get_user(validated_token=decoded_data)
        return await super().__call__(scope, receive, send)


def JwtAuthMiddlewareStack(inner):
    return JwtAuthMiddleware(AuthMiddlewareStack(inner))
















# """General web socket middlewares with JWT auth and audit logging"""
# from channels.db import database_sync_to_async
# from django.contrib.auth import get_user_model
# from django.contrib.auth.models import AnonymousUser
# from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
# from rest_framework_simplejwt.tokens import UntypedToken
# from rest_framework_simplejwt.authentication import JWTTokenUserAuthentication
# from django.contrib.auth.models import User
# from channels.middleware import BaseMiddleware
# from channels.auth import AuthMiddlewareStack
# from django.db import close_old_connections
# from urllib.parse import parse_qs
# from jwt import decode as jwt_decode
# from django.conf import settings
# import json
# from django.utils import timezone
# from user_management.models import AuditLog

# @database_sync_to_async
# def get_user(validated_token):
#     try:
#         user = get_user_model().objects.get(id=validated_token["user_id"])
#         return user
#     except User.DoesNotExist:
#         return AnonymousUser()

# @database_sync_to_async
# def create_audit_log(user, action, ip_address, user_agent, metadata):
#     if not user or user.is_anonymous:
#         return
    
#     AuditLog.objects.create(
#         u_id=user,
#         a_action=action,
#         a_ip_address=ip_address,
#         a_user_agent=user_agent,
#         a_metadata=metadata,
#         created_at=timezone.now(),
#         updated_at=timezone.now()
#     )

# class JwtAuthMiddleware(BaseMiddleware):
#     def __init__(self, inner):
#         self.inner = inner

#     async def __call__(self, scope, receive, send):
#         # Close old database connections
#         close_old_connections()

#         # Initialize audit log data
#         ip_address = self.get_client_ip(scope)
#         user_agent = self.get_user_agent(scope)
#         path = scope.get('path', '')
        
#         try:
#             # Get token from query string or headers
#             token = self.get_token_from_scope(scope)
#             if not token:
#                 scope["user"] = AnonymousUser()
#                 return await super().__call__(scope, receive, send)

#             # Validate token
#             UntypedToken(token)
            
#             # Decode token and get user
#             decoded_data = jwt_decode(token, settings.SECRET_KEY, algorithms=["HS256"])
#             user = await get_user(validated_token=decoded_data)
#             scope["user"] = user
            
#             # Create connection audit log
#             await create_audit_log(
#                 user=user,
#                 action=f"WS_CONNECT {path}",
#                 ip_address=ip_address,
#                 user_agent=user_agent,
#                 metadata=json.dumps({
#                     'path': path,
#                     'query_string': scope.get('query_string', b'').decode(),
#                     'status': 'connected'
#                 })
#             )
            
#         except (InvalidToken, TokenError, KeyError) as e:
#             scope["user"] = AnonymousUser()
            
#             # Create failed connection audit log
#             await create_audit_log(
#                 user=None,
#                 action=f"WS_CONNECT_FAILED {path}",
#                 ip_address=ip_address,
#                 user_agent=user_agent,
#                 metadata=json.dumps({
#                     'path': path,
#                     'error': str(e),
#                     'status': 'authentication_failed'
#                 })
#             )
            
#         return await super().__call__(scope, receive, send)

#     def get_token_from_scope(self, scope):
#         """Extract token from query string or headers"""
#         # Try query string first
#         try:
#             query_string = parse_qs(scope["query_string"].decode("utf8"))
#             return query_string.get("token", [None])[0]
#         except (KeyError, AttributeError):
#             pass
        
#         # Try headers
#         headers = dict(scope.get('headers', []))
#         if b'authorization' in headers:
#             auth_header = headers[b'authorization'].decode()
#             if auth_header.startswith('Bearer '):
#                 return auth_header.split(' ')[1]
#         return None

#     def get_client_ip(self, scope):
#         """Get client IP from scope"""
#         client = scope.get('client', ('', 0))
#         return client[0]

#     def get_user_agent(self, scope):
#         """Get user agent from scope headers"""
#         headers = dict(scope.get('headers', []))
#         return next((v.decode() for k, v in headers if k.lower() == b'user-agent'), '')


# class AuditLogMiddleware:
#     """WebSocket audit logging middleware"""
#     def __init__(self, app):
#         self.app = app

#     async def __call__(self, scope, receive, send):
#         # Only process WebSocket connections
#         if scope['type'] != 'websocket':
#             return await self.app(scope, receive, send)

#         # Get connection info
#         user = scope.get('user', AnonymousUser())
#         ip_address = self.get_client_ip(scope)
#         user_agent = self.get_user_agent(scope)
#         path = scope.get('path', '')

#         # Log connection attempt
#         try:
#             await create_audit_log(
#                 user=user if not user.is_anonymous else None,
#                 action=f"WS_CONNECT_ATTEMPT {path}",
#                 ip_address=ip_address,
#                 user_agent=user_agent,
#                 metadata=json.dumps({
#                     'path': path,
#                     'query_string': scope.get('query_string', b'').decode()
#                 })
#             )
#         except Exception as e:
#             pass  # Don't break connection if logging fails

#         # Handle the connection
#         try:
#             return await self.app(scope, receive, send)
#         finally:
#             # Log disconnection
#             try:
#                 await create_audit_log(
#                     user=user if not user.is_anonymous else None,
#                     action=f"WS_DISCONNECT {path}",
#                     ip_address=ip_address,
#                     user_agent=user_agent,
#                     metadata=json.dumps({
#                         'path': path,
#                         'duration': 'N/A',  # You could track connection duration here
#                         'status': 'disconnected'
#                     })
#                 )
#             except Exception as e:
#                 pass  # Don't break connection if logging fails

#     def get_client_ip(self, scope):
#         """Get client IP from scope"""
#         client = scope.get('client', ('', 0))
#         return client[0]

#     def get_user_agent(self, scope):
#         """Get user agent from scope headers"""
#         headers = dict(scope.get('headers', []))
#         return next((v.decode() for k, v in headers if k.lower() == b'user-agent'), '')


# def JwtAuthMiddlewareStack(inner):
#     """Stack of middlewares for WebSocket connections"""
#     return JwtAuthMiddleware(AuditLogMiddleware(AuthMiddlewareStack(inner)))