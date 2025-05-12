from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

ERROR_CODES = {
    'authentication_failed': 1001,
    'invalid_token': 1002,
    'token_expired': 1003,
    'permission_denied': 1004,
    'not_found': 1005,
    'validation_error': 1006,
    'server_error': 1007,
    'bad_request': 1008,
}

def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    
    if response is not None:
        error_message = response.data
        error_code = ERROR_CODES.get('server_error')
        
        if hasattr(exc, 'detail'):
            if isinstance(exc.detail, dict):
                error_message = exc.detail
            else:
                error_message = {'detail': str(exc.detail)}
        
        # Map exception to error code
        if response.status_code == 401:
            error_code = ERROR_CODES.get('authentication_failed')
        elif response.status_code == 403:
            error_code = ERROR_CODES.get('permission_denied')
        elif response.status_code == 404:
            error_code = ERROR_CODES.get('not_found')
        elif response.status_code == 400:
            error_code = ERROR_CODES.get('validation_error')
        
        # Format the response
        response.data = {
            'success': False,
            'error_code': error_code,
            'message': error_message,
            'status_code': response.status_code
        }
    
    return response


