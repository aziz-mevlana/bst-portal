"""One bounded query projection reused by the student dashboard and course list."""
from django.db.models import Prefetch, Q
from django.utils import timezone
from .course_work_models import CourseProjectParticipation, CourseProjectWork
from .models import ProjectMilestone


def student_course_assignments(user):
    participations = list(CourseProjectParticipation.objects.filter(student=user)
        .select_related('assignment__course','assignment__instructor','team').order_by('-joined_at'))
    works = CourseProjectWork.objects.filter(
        Q(owner=user) | Q(team_id__in=[item.team_id for item in participations if item.team_id])
    ).select_related('project').prefetch_related(Prefetch('project__milestones',
        queryset=ProjectMilestone.objects.select_related('assignment_checkpoint').prefetch_related('submissions__review')))
    by_owner, by_team = {}, {}
    for work in works:
        (by_team if work.team_id else by_owner)[work.team_id or work.assignment_id] = work
    now = timezone.now()
    for item in participations:
        work = by_team.get(item.team_id) if item.team_id else by_owner.get(item.assignment_id)
        if work and work.assignment_id != item.assignment_id:
            work = None
        item.work_id = work.pk if work else None
        item.project_title = work.project.title if work else 'Proje hazırlığı'
        milestones = [m for m in work.project.milestones.all() if m.assignment_checkpoint and m.assignment_checkpoint.is_active] if work else []
        item.completed_count = sum(m.state == 'APPROVED' for m in milestones)
        item.total_count = len(milestones)
        item.next_checkpoint = next((m for m in milestones if m.state != 'APPROVED'), None)
        item.overdue = bool(item.next_checkpoint and item.next_checkpoint.effective_due_at < now)
        item.status_label = ('Aktif' if item.assignment.is_active else 'Geçmiş · Salt okunur')
    return participations
