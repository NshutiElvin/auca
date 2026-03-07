from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsInstructor(BasePermission):
    """
    Grants access to users who are staff members (instructors).
    Adjust the condition to match your user role setup
    (e.g. user.profile.role == 'instructor').
    """
    message = "Only instructors can perform this action."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


class IsAdminUser(BasePermission):
    """
    Grants access only to superusers / admins.
    """
    message = "Only admins can perform this action."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class IsReportOwnerOrAdmin(BasePermission):
    """
    Object-level permission:
    - Admins can do anything.
    - Instructors can only read their own reports.
    """
    message = "You do not have permission to access this report."

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.method in SAFE_METHODS:
            return obj.reported_by == request.user
        return False