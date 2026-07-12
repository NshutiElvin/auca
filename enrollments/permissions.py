from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdminOrInstructor(BasePermission):
    """
    Allow create/update/delete only for users with role 'admin' or 'instructor'.
    Everyone can read.
    """
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_authenticated and request.user.role in ['admin', 'instructor']


class IsStudent(BasePermission):
    """
    Allow only students to create enrollments. Others can read.
    """
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_authenticated and request.user.role == 'student'


class IsEnrollmentOwnerOrStaff(BasePermission):
    """
    Object-level check for update/partial_update/destroy on an Enrollment.

    `IsStudent` only confirms the requester IS *a* student — it never checked
    *whose* enrollment they were touching. Combined with a fully writable
    serializer (amount_paid, amount_to_pay, status, final_grade) and an
    unfiltered queryset, that let any student edit or delete any *other*
    student's enrollment (including marking it as fully paid, or deleting it
    outright). This adds the missing "is this actually your row" check.
    """
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_authenticated and request.user.role in (
            'student', 'admin', 'instructor'
        )

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if request.user.role in ('admin', 'instructor'):
            return True
        return getattr(obj.student, 'user_id', None) == request.user.id
