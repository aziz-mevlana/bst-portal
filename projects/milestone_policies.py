from accounts.policies import is_admin, is_teacher
from .models import CourseInstructor


def _generic(project):
    return project.project_type.code != 'CAPSTONE'


def can_manage_project_milestones(user, project):
    work = getattr(project, 'course_project_work', None)
    if work:
        return bool(user.is_authenticated and user.is_active and _generic(project) and (
            is_admin(user) or is_teacher(user) and work.assignment.instructor_id == user.pk and
            CourseInstructor.objects.filter(course_id=work.assignment.course_id, instructor=user, is_active=True).exists()
        ))
    return bool(user.is_authenticated and user.is_active and _generic(project) and (
        is_admin(user) or (is_teacher(user) and project.advisor_id == user.pk) or (
            project.course_id and is_teacher(user) and CourseInstructor.objects.filter(
                course_id=project.course_id, instructor=user, is_active=True
            ).exists()
        )
    ))


def can_submit_project_milestone(user, milestone):
    project = milestone.project
    work = getattr(project, 'course_project_work', None)
    if work:
        from .course_work_models import CourseProjectParticipation
        if not milestone.assignment_checkpoint_id or not milestone.assignment_checkpoint.is_active:
            return False
        participants = CourseProjectParticipation.objects.filter(assignment=work.assignment, student=user)
        if work.owner_id:
            participants = participants.filter(student_id=work.owner_id)
        else:
            participants = participants.filter(team_id=work.team_id)
            if work.team.participants.count() < work.assignment.min_team_size:
                return False
        return bool(user.is_authenticated and user.is_active and _generic(project) and participants.exists())
    return bool(user.is_authenticated and user.is_active and _generic(project) and (
        project.created_by_id == user.pk or project.team.filter(pk=user.pk).exists()
    ))


def can_review_project_milestone(user, milestone):
    return can_manage_project_milestones(user, milestone.project)


def can_view_project_milestone_evidence(user, submission):
    project = submission.milestone.project
    work = getattr(project, 'course_project_work', None)
    if work:
        from .course_work_models import CourseProjectParticipation
        participant = CourseProjectParticipation.objects.filter(assignment=work.assignment, student=user)
        participant = participant.filter(student_id=work.owner_id) if work.owner_id else participant.filter(team_id=work.team_id)
        return bool(user.is_authenticated and user.is_active and _generic(project) and (
            can_manage_project_milestones(user, project) or participant.exists()
        ))
    return bool(user.is_authenticated and user.is_active and _generic(project) and (
        can_manage_project_milestones(user, project)
        or project.created_by_id == user.pk
        or project.team.filter(pk=user.pk).exists()
    ))
