from django.core.exceptions import ObjectDoesNotExist

from accounts.policies import is_admin, role_of

from .models import CapstoneEnrollment, CapstoneTerm


def _authenticated_user(user):
    return bool(user is not None and getattr(user, 'is_authenticated', False))


def _capstone_project_base(capstone_project):
    if capstone_project is None:
        return None
    try:
        return capstone_project.project
    except (AttributeError, ObjectDoesNotExist):
        return None


def is_capstone_eligible_student(user, term=None):
    """Return whether a user is an actively enrolled fourth-year student."""

    if not getattr(user, 'is_authenticated', False) or not user.is_active:
        return False
    profile = getattr(user, 'profile', None)
    if profile is None or role_of(user) not in {'student', 'staff_student'}:
        return False
    if profile.class_level != '4':
        return False
    if term is None:
        term = CapstoneTerm.objects.filter(is_active=True).first()
    if term is None or term.pk is None:
        return False
    return CapstoneEnrollment.objects.filter(
        term=term,
        student=user,
        is_active=True,
    ).exists()


def can_view_capstone(user, capstone_project):
    project = _capstone_project_base(capstone_project)
    if project is None or not _authenticated_user(user):
        return False
    return bool(
        user.pk == project.created_by_id
        or (user.is_active and role_of(user) == 'teacher' and user.pk == project.advisor_id)
        or is_admin(user)
    )


def can_review_capstone_proposal(user, proposal):
    return bool(_authenticated_user(user) and (
        is_admin(user) or (
            user.is_active and role_of(user) == 'teacher' and user.pk == proposal.requested_advisor_id
        )
    ))


def can_view_capstone_proposal(user, proposal):
    return bool(_authenticated_user(user) and (
        user.pk == proposal.student_id or can_review_capstone_proposal(user, proposal)
    ))


def can_submit_capstone(user, capstone_project):
    project = _capstone_project_base(capstone_project)
    if project is None or not _authenticated_user(user) or not user.is_active:
        return False
    return bool(
        user.pk == project.created_by_id
        and role_of(user) in {'student', 'staff_student'}
        and project.advisor_id is not None
    )


def can_review_capstone(user, capstone_project):
    project = _capstone_project_base(capstone_project)
    if project is None or not project.advisor_id or not _authenticated_user(user):
        return False
    if is_admin(user):
        return True
    return bool(
        user.is_active
        and user.pk == project.advisor_id
        and role_of(user) == 'teacher'
    )


def can_administer_capstone(user, capstone_project):
    if _capstone_project_base(capstone_project) is None or not _authenticated_user(user):
        return False
    return is_admin(user)
