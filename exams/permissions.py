from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdminOrInstructor(BasePermission):
    """
    Allow create/update/delete only for users with role 'admin' or 'instructor'.
    Everyone can read.
    """
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return request.user.role in ['admin', 'instructor']


class IsStudent(BasePermission):
    """
    Allow only students to create enrollments. Others can read.
    """
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return request.user.role == 'student'
