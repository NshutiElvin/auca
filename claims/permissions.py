from rest_framework.permissions import BasePermission


class IsClaimManager(BasePermission):
    """
    Admins (role='admin' or is_staff) OR any user explicitly granted the
    'change_claimresponse' Django permission may update/resolve claims or
    manage claim responses.

    The frontend already gates its claim-management UI (status-change
    buttons, response form) on exactly this permission for non-admin staff
    (see ClaimDetailPage.tsx: `isAdmin || hasPermission(CHANGE_CLAIMRESPONSE)`)
    — a blanket admin-only check here would silently break that intended
    tier. It still closes the actual bug (a student with no granted
    permissions self-approving their own claim), since students don't hold
    this permission by default.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_staff or getattr(user, "role", None) == "admin":
            return True
        return user.has_perm("claims.change_claimresponse")
