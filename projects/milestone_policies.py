from accounts.policies import is_admin, is_teacher
from .models import CourseInstructor


def _generic(project):
    return project.project_type.code != 'CAPSTONE'


def can_manage_project_milestones(user, project):
    return bool(user.is_authenticated and _generic(project) and (
        is_admin(user) or project.advisor_id == user.pk or (
            project.course_id and is_teacher(user) and CourseInstructor.objects.filter(
                course_id=project.course_id, instructor=user, is_active=True
            ).exists()
        )
    ))


def can_submit_project_milestone(user, milestone):
    project = milestone.project
    return bool(user.is_authenticated and _generic(project) and (
        project.created_by_id == user.pk or project.team.filter(pk=user.pk).exists()
    ))


def can_review_project_milestone(user, milestone):
    return can_manage_project_milestones(user, milestone.project)


def can_view_project_milestone_evidence(user, submission):
    project = submission.milestone.project
    return bool(user.is_authenticated and _generic(project) and (
        can_manage_project_milestones(user, project)
        or project.created_by_id == user.pk
        or project.team.filter(pk=user.pk).exists()
    ))
