from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdminOrInstructor(BasePermission):
    
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return request.user.role in ['admin', 'instructor']


class IsStudent(BasePermission):
  
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return request.user.role == 'student'
