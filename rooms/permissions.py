from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdminOrInstructor(BasePermission):
    """
    Allow create/update/delete only for users with role 'admin' or
    'instructor'. Everyone authenticated can read.

    Uses the app's actual role field rather than DRF's IsAdminUser
    (Django is_staff) — role="admin" accounts created through this app's
    own user-management UI never get is_staff=True (forced False on
    creation to prevent privilege escalation), so IsAdminUser rejects
    every real admin. Same fix already applied in exams/views.py.
    """
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ['admin', 'instructor']
        )
