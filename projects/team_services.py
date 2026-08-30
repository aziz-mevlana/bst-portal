from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from core.audit import record_audit_event
from core.notifications import create_notification
from accounts.policies import is_admin

from .models import Team, TeamInvitation, TeamMembership


def can_disband_team(user, team):
    return bool(user.is_authenticated and (is_admin(user) or team.leader_id == user.pk))


@transaction.atomic
def create_team(*, leader, form, request=None):
    team = form.save(commit=False)
    team.leader = leader
    team.save()
    form.save_m2m()
    TeamMembership.objects.create(team=team, user=leader, role='Ekip lideri')
    record_audit_event(actor=leader, action='team.created', target=team, request=request)
    return team


@transaction.atomic
def invite_user(*, team, inviter, invited_user, proposed_role='', request=None):
    locked_team = Team.objects.select_for_update().get(pk=team.pk)
    if locked_team.leader_id != inviter.pk:
        raise PermissionDenied
    if invited_user.pk == inviter.pk or TeamMembership.objects.filter(team=team, user=invited_user).exists():
        raise ValidationError('Bu kullanıcı zaten ekibin üyesi.')
    try:
        invitation = TeamInvitation.objects.create(
            team=team, invited_user=invited_user, invited_by=inviter,
            proposed_role=proposed_role.strip(),
        )
    except IntegrityError as exc:
        raise ValidationError('Bu kullanıcı için zaten bekleyen bir davet var.') from exc
    create_notification(
        recipient=invited_user, actor=inviter, notification_type='team_invite',
        title='Ekip daveti', message=f'{team.name} ekibine davet edildiniz.',
        target_url=reverse('projects:team_invitations'), dedupe_key=f'team-invite:{invitation.pk}',
    )
    record_audit_event(actor=inviter, action='team.invited', target=invitation, request=request)
    return invitation


@transaction.atomic
def respond_to_invitation(*, invitation_id, user, accept, request=None):
    invitation = TeamInvitation.objects.select_for_update().select_related('team').get(pk=invitation_id)
    if invitation.invited_user_id != user.pk:
        raise PermissionDenied
    if invitation.status == 'accepted' and accept:
        return TeamMembership.objects.get(team=invitation.team, user=user)
    if invitation.status != 'pending':
        raise ValidationError('Bu davet daha önce sonuçlandırılmış.')
    membership = None
    if accept:
        membership, _ = TeamMembership.objects.get_or_create(
            team=invitation.team, user=user, defaults={'role': invitation.proposed_role}
        )
        invitation.status = 'accepted'
    else:
        invitation.status = 'rejected'
    invitation.responded_at = timezone.now()
    invitation.save(update_fields=['status', 'responded_at'])
    create_notification(
        recipient=invitation.team.leader, actor=user, notification_type='team_invite_result',
        title='Ekip daveti yanıtlandı',
        message=f'{user.get_full_name() or user.username} daveti {"kabul etti" if accept else "reddetti"}.',
        target_url=invitation.team.get_absolute_url(),
        dedupe_key=f'team-invite-result:{invitation.pk}',
    )
    record_audit_event(actor=user, action='team.invite_accepted' if accept else 'team.invite_rejected', target=invitation, request=request)
    return membership


@transaction.atomic
def cancel_invitation(*, invitation_id, user, request=None):
    invitation = TeamInvitation.objects.select_for_update().select_related('team').get(pk=invitation_id)
    if invitation.team.leader_id != user.pk:
        raise PermissionDenied
    if invitation.status != 'pending':
        raise ValidationError('Yalnızca bekleyen davetler iptal edilebilir.')
    invitation.status = 'cancelled'
    invitation.responded_at = timezone.now()
    invitation.save(update_fields=['status', 'responded_at'])
    record_audit_event(actor=user, action='team.invite_cancelled', target=invitation, request=request)
    return invitation


@transaction.atomic
def disband_team(*, team, actor, request=None):
    """Delete the team container while preserving every linked project."""

    locked_team = Team.objects.select_for_update().select_related('leader').get(pk=team.pk)
    if not can_disband_team(actor, locked_team):
        raise PermissionDenied('Bu ekibi dağıtma yetkiniz yok.')

    member_ids = list(locked_team.members.exclude(pk=actor.pk).values_list('pk', flat=True))
    linked_project_ids = list(locked_team.projects.values_list('pk', flat=True))
    record_audit_event(
        actor=actor,
        action='team.disbanded',
        target=locked_team,
        request=request,
        metadata={
            'team_name': locked_team.name,
            'leader_id': locked_team.leader_id,
            'member_count': locked_team.members.count(),
            'linked_project_ids': linked_project_ids,
        },
    )
    for member in User.objects.filter(pk__in=member_ids):
        create_notification(
            recipient=member,
            actor=actor,
            notification_type='system',
            title='Ekip dağıtıldı',
            message=f'{locked_team.name} ekibi dağıtıldı. Ekibe bağlı projeler korunmaya devam ediyor.',
            target_url=reverse('projects:team_list'),
            dedupe_key=f'team-disbanded:{locked_team.pk}:{member.pk}',
            force=True,
        )
    team_name = locked_team.name
    locked_team.delete()
    return team_name
