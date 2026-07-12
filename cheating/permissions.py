from rest_framework.permissions import BasePermission, SAFE_METHODS


def _is_admin(user):
    # This app's real admin accounts are created with role='admin' (see
    # users/serializers.py), not Django's is_staff/is_superuser flags — a
    # check that only looked at is_superuser would both lock out legitimate
    # app-admins and (previously) let is_staff be spoofed at registration.
    return bool(user.is_superuser or getattr(user, "role", None) == "admin")


class IsInstructor(BasePermission):
    """
    Grants access to instructors (or admins).
    """
    message = "Only instructors can perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and (request.user.is_staff or getattr(request.user, "role", None) in ("instructor", "admin"))
        )


class IsAdminUser(BasePermission):
    """
    Grants access only to superusers / admins.
    """
    message = "Only admins can perform this action."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and _is_admin(request.user))


class IsReportOwnerOrAdmin(BasePermission):
    """
    Object-level permission:
    - Admins can do anything.
    - Instructors can only read their own reports.
    """
    message = "You do not have permission to access this report."

    def has_object_permission(self, request, view, obj):
        if _is_admin(request.user):
            return True
        if request.method in SAFE_METHODS:
            return obj.reported_by == request.user
        return False