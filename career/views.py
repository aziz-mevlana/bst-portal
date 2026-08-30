from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from alumni.models import Alumni
from core.audit import record_audit_event
from core.analytics import record_analytics_event
from core.notifications import create_notification
from core.rate_limit import is_rate_limited
from projects.models import ProjectCategory, Technology
from accounts.email_service import EmailConfigurationError, send_transactional_email
from accounts.models import EmailVerification
from accounts.permissions import ensure_interactive_account

from .forms import (
    CollaborationRequestForm,
    CollaborationReviewForm,
    MentorshipProfileForm,
    MentorshipRequestForm,
    MentorshipResponseForm,
    MentorshipReviewForm,
    OpportunityForm,
)
from .models import CollaborationRequest, MentorshipProfile, MentorshipRequest, MentorshipReview, Opportunity
from .collaboration_service import publish_collaboration


def collaboration_create(request):
    if request.method == 'POST' and is_rate_limited(request, scope='collaboration-create', limit=5, window_seconds=3600):
        return render(request, 'career/collaboration_form.html', {'form': CollaborationRequestForm(request.POST)}, status=429)
    if request.method == 'POST':
        form = CollaborationRequestForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.email = item.email.strip().lower()
            item.consent_at = timezone.now()
            code = EmailVerification.generate_code()
            try:
                with transaction.atomic():
                    item.save()
                    verification = EmailVerification(
                        email=item.email,
                        session_data={'purpose': 'collaboration', 'collaboration_id': item.pk},
                    )
                    verification.set_code(code)
                    verification.save()
                    send_transactional_email(
                        'BST Akademi - İş birliği talebi doğrulama kodu',
                        f'Merhaba {item.contact_name},\n\nDoğrulama kodunuz: {code}\n\nKod 10 dakika geçerlidir.\nTakip numaranız: {item.tracking_number}',
                        item.email,
                    )
            except EmailConfigurationError:
                messages.error(request, 'E-posta servisi şu anda yapılandırılmamış. Lütfen daha sonra tekrar deneyin.')
            except Exception:
                messages.error(request, 'Doğrulama e-postası gönderilemedi. Lütfen tekrar deneyin.')
            else:
                request.session['collaboration_id'] = item.pk
                messages.success(request, 'Doğrulama kodu e-posta adresinize gönderildi.')
                return redirect('career:collaboration_verify')
    else:
        form = CollaborationRequestForm()
    return render(request, 'career/collaboration_form.html', {'form': form})


def collaboration_verify(request):
    item_id = request.session.get('collaboration_id')
    item = CollaborationRequest.objects.filter(pk=item_id, status='pending_email').first()
    if not item:
        messages.error(request, 'Doğrulanmayı bekleyen bir iş birliği talebi bulunamadı.')
        return redirect('career:collaboration_create')
    verification = EmailVerification.objects.filter(email=item.email, is_verified=False).order_by('-created_at').first()
    if not verification or verification.session_data.get('purpose') != 'collaboration' or verification.session_data.get('collaboration_id') != item.pk:
        messages.error(request, 'Doğrulama kaydı bulunamadı.')
        return redirect('career:collaboration_create')
    if request.method == 'POST':
        if is_rate_limited(request, scope='collaboration-verify', limit=15, window_seconds=600):
            messages.error(request, 'Çok fazla doğrulama denemesi yapıldı.')
            return redirect('career:collaboration_verify')
        code = request.POST.get('code', '').strip()
        if verification.is_expired():
            messages.error(request, 'Doğrulama kodunun süresi doldu. Lütfen formu yeniden gönderin.')
            return redirect('career:collaboration_create')
        if verification.failed_attempts >= 5 or not verification.matches_code(code):
            verification.failed_attempts += 1
            verification.save(update_fields=['failed_attempts'])
            messages.error(request, 'Doğrulama kodu hatalı veya deneme sınırı aşıldı.')
            return redirect('career:collaboration_verify')
        with transaction.atomic():
            item = CollaborationRequest.objects.select_for_update().get(pk=item.pk)
            item.email_verified_at = timezone.now()
            item.status = 'pending_review'
            item.save(update_fields=['email_verified_at', 'status', 'updated_at'])
            verification.is_verified = True
            verification.save(update_fields=['is_verified'])
        request.session.pop('collaboration_id', None)
        return render(request, 'career/collaboration_success.html', {'item': item})
    return render(request, 'career/collaboration_verify.html', {'item': item})


@login_required
def collaboration_manage(request):
    if not _can_review_collaboration(request.user):
        raise PermissionDenied
    items = CollaborationRequest.objects.select_related('assigned_teacher', 'reviewed_by').order_by('-created_at')
    status = request.GET.get('status', '')
    query = request.GET.get('q', '').strip()
    if status:
        items = items.filter(status=status)
    if query:
        items = items.filter(Q(tracking_number__icontains=query) | Q(organization__icontains=query) | Q(title__icontains=query))
    return render(request, 'career/collaboration_manage.html', {
        'items': items, 'statuses': CollaborationRequest.STATUS_CHOICES, 'selected_status': status, 'query': query,
    })


@login_required
def collaboration_review(request, request_id):
    if not _can_review_collaboration(request.user):
        raise PermissionDenied
    item = get_object_or_404(CollaborationRequest, pk=request_id)
    if request.method == 'POST':
        form = CollaborationReviewForm(request.POST, instance=item)
        action = request.POST.get('action')
        if form.is_valid():
            item = form.save()
            if action == 'reject':
                item.status = 'rejected'
                item.reviewed_by = request.user
                item.reviewed_at = timezone.now()
                item.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])
                record_audit_event(actor=request.user, action='collaboration.rejected', target=item, request=request)
                messages.success(request, 'Talep reddedildi.')
                return redirect('career:collaboration_manage')
            if action == 'first_review':
                if not request.user.has_perm('accounts.review_collaborations'):
                    raise PermissionDenied
                item.status = 'approved'
                item.reviewed_by = request.user
                item.reviewed_at = timezone.now()
                item.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])
                record_audit_event(
                    actor=request.user,
                    action='collaboration.first_reviewed',
                    target=item,
                    request=request,
                    metadata={'publication_channel': item.publication_channel},
                )
                messages.success(request, 'İlk inceleme tamamlandı; talep yönetici yayınına hazır.')
                return redirect('career:collaboration_review', request_id=item.pk)
            if not (request.user.is_staff or request.user.is_superuser):
                raise PermissionDenied
            try:
                publish_collaboration(item.pk, request.user)
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                record_audit_event(actor=request.user, action='collaboration.published', target=item, request=request)
                messages.success(request, 'Talep uygun kanalda yayımlandı.')
                return redirect('career:collaboration_review', request_id=item.pk)
    else:
        form = CollaborationReviewForm(instance=item, initial={
            'normalized_title': item.normalized_title or item.title,
            'normalized_description': item.normalized_description or item.description,
        })
    return render(request, 'career/collaboration_review.html', {
        'item': item,
        'form': form,
        'can_publish': request.user.is_staff or request.user.is_superuser,
        'can_first_review': request.user.has_perm('accounts.review_collaborations'),
    })


def _can_review_collaboration(user):
    return bool(
        user.is_authenticated
        and (user.is_staff or user.is_superuser or user.has_perm('accounts.review_collaborations'))
    )


def _is_staff(user):
    profile = getattr(user, 'profile', None) if user.is_authenticated else None
    return bool(user.is_authenticated and (user.is_staff or user.is_superuser or getattr(profile, 'user_type', '') == 'staff_student'))


def _is_django_admin(user):
    return bool(user.is_authenticated and (user.is_staff or user.is_superuser))


def _can_edit_opportunity(user, opportunity):
    return bool(user.is_authenticated and (_is_django_admin(user) or opportunity.created_by_id == user.pk))


def _can_publish_opportunity(user):
    profile = getattr(user, 'profile', None) if user.is_authenticated else None
    return bool(user.is_authenticated and (_is_staff(user) or getattr(profile, 'user_type', '') in {'teacher', 'alumni'}))


def opportunity_list(request):
    scope = request.GET.get('scope', '')
    opportunities = Opportunity.objects.select_related('created_by').prefetch_related('technologies')
    if scope == 'all' and _is_django_admin(request.user):
        pass
    elif scope == 'mine' and request.user.is_authenticated:
        opportunities = opportunities.filter(created_by=request.user)
    else:
        scope = ''
        opportunities = opportunities.filter(
            approval_status='approved', is_active=True,
        ).filter(Q(deadline__isnull=True) | Q(deadline__gte=timezone.localdate()))
    query = request.GET.get('q', '').strip()
    kind = request.GET.get('type', '')
    work_mode = request.GET.get('work_mode', '')
    technology = request.GET.get('technology', '')
    if query:
        opportunities = opportunities.filter(Q(title__icontains=query) | Q(organization__icontains=query) | Q(description__icontains=query))
    if kind:
        opportunities = opportunities.filter(opportunity_type=kind)
    if work_mode:
        opportunities = opportunities.filter(work_mode=work_mode)
    if technology:
        opportunities = opportunities.filter(technologies__pk=technology)
    return render(request, 'career/opportunity_list.html', {
        'opportunities': opportunities.distinct(),
        'types': Opportunity.TYPE_CHOICES,
        'work_modes': Opportunity.WORK_MODE_CHOICES,
        'technologies': Technology.objects.filter(is_active=True),
        'can_publish': _can_publish_opportunity(request.user),
        'can_manage_all': _is_django_admin(request.user),
        'selected_scope': scope,
        'selected': request.GET,
    })


def opportunity_detail(request, slug):
    opportunity = get_object_or_404(Opportunity.objects.prefetch_related('technologies'), slug=slug)
    if not opportunity.is_open and not (_is_staff(request.user) or opportunity.created_by_id == getattr(request.user, 'id', None)):
        raise Http404
    return render(request, 'career/opportunity_detail.html', {
        'opportunity': opportunity,
        'meta_title': f'{opportunity.title} | BST Kariyer',
        'meta_description': opportunity.description[:160],
        'canonical_url': request.build_absolute_uri(opportunity.get_absolute_url()),
        'meta_robots': 'index,follow' if opportunity.is_open else 'noindex,nofollow',
        'can_moderate': _is_staff(request.user),
        'can_edit': _can_edit_opportunity(request.user, opportunity),
        'can_delete': _can_edit_opportunity(request.user, opportunity),
    })


@login_required
def opportunity_create(request):
    if not _can_publish_opportunity(request.user):
        raise PermissionDenied
    if request.method == 'POST':
        form = OpportunityForm(request.POST)
        if form.is_valid():
            opportunity = form.save(commit=False)
            opportunity.created_by = request.user
            if _is_staff(request.user):
                opportunity.approval_status = 'approved'
                opportunity.approved_by = request.user
                opportunity.approved_at = timezone.now()
            opportunity.save()
            form.save_m2m()
            record_audit_event(actor=request.user, action='opportunity.created', target=opportunity, request=request)
            messages.success(request, 'İlan yayımlandı.' if opportunity.approval_status == 'approved' else 'İlan yönetici onayına gönderildi.')
            return redirect(opportunity.get_absolute_url())
    else:
        form = OpportunityForm()
    return render(request, 'career/opportunity_form.html', {'form': form})


@login_required
def opportunity_edit(request, opportunity_id):
    opportunity = get_object_or_404(Opportunity, pk=opportunity_id)
    if not _can_edit_opportunity(request.user, opportunity):
        raise PermissionDenied
    if request.method == 'POST':
        form = OpportunityForm(request.POST, instance=opportunity)
        if form.is_valid():
            opportunity = form.save(commit=False)
            if not _is_django_admin(request.user):
                opportunity.approval_status = 'pending'
                opportunity.approved_by = None
                opportunity.approved_at = None
            opportunity.save()
            form.save_m2m()
            record_audit_event(actor=request.user, action='opportunity.updated', target=opportunity, request=request)
            messages.success(
                request,
                'İlan güncellendi.' if opportunity.approval_status == 'approved'
                else 'İlan güncellendi ve yeniden yönetici onayına gönderildi.',
            )
            return redirect(opportunity.get_absolute_url())
    else:
        form = OpportunityForm(instance=opportunity)
    return render(request, 'career/opportunity_form.html', {
        'form': form,
        'opportunity': opportunity,
        'is_edit': True,
    })


@login_required
@require_POST
def opportunity_delete(request, opportunity_id):
    opportunity = get_object_or_404(Opportunity.objects.select_related('created_by'), pk=opportunity_id)
    if not _can_edit_opportunity(request.user, opportunity):
        raise PermissionDenied
    if request.POST.get('confirm_delete') != 'yes':
        messages.error(request, 'Kariyer ilanını silmek için işlemi onaylamalısınız.')
        return redirect(opportunity.get_absolute_url())

    title = opportunity.title
    creator = opportunity.created_by
    record_audit_event(
        actor=request.user,
        action='opportunity.deleted',
        target=opportunity,
        request=request,
        metadata={'title': title, 'organization': opportunity.organization, 'created_by_id': opportunity.created_by_id},
    )
    opportunity.delete()
    if creator and creator != request.user:
        create_notification(
            recipient=creator,
            actor=request.user,
            notification_type='moderation',
            title='Kariyer ilanı silindi',
            message=f'“{title}” kariyer ilanı bir yönetici tarafından silindi.',
            target_url='/career/?scope=mine',
            force=True,
        )
    messages.success(request, 'Kariyer ilanı kalıcı olarak silindi.')
    return redirect(f"{reverse('career:opportunity_list')}?scope={'all' if _is_django_admin(request.user) else 'mine'}")


@login_required
@require_POST
def opportunity_approve(request, opportunity_id):
    if not _is_staff(request.user):
        raise PermissionDenied
    opportunity = get_object_or_404(Opportunity, pk=opportunity_id)
    opportunity.approval_status = 'approved'
    opportunity.approved_by = request.user
    opportunity.approved_at = timezone.now()
    opportunity.save(update_fields=['approval_status', 'approved_by', 'approved_at', 'updated_at'])
    create_notification(recipient=opportunity.created_by, actor=request.user, notification_type='opportunity', message=f'“{opportunity.title}” ilanı onaylandı.', target_url=opportunity.get_absolute_url())
    record_audit_event(actor=request.user, action='opportunity.approved', target=opportunity, request=request)
    messages.success(request, 'İlan onaylandı.')
    return redirect(opportunity.get_absolute_url())


@login_required
def mentor_list(request):
    mentors = MentorshipProfile.objects.filter(is_available=True, alumni__is_show_in_alumni_list=True, alumni__user__is_active=True).select_related('alumni', 'alumni__user').prefetch_related('mentoring_topics')
    topic = request.GET.get('topic', '')
    query = request.GET.get('q', '').strip()
    if topic:
        mentors = mentors.filter(mentoring_topics__pk=topic)
    if query:
        mentors = mentors.filter(Q(alumni__full_name__icontains=query) | Q(alumni__user__first_name__icontains=query) | Q(alumni__user__last_name__icontains=query) | Q(alumni__current_position__icontains=query) | Q(alumni__company__icontains=query))
    return render(request, 'career/mentor_list.html', {'mentors': mentors.distinct(), 'topics': ProjectCategory.objects.filter(is_active=True)})


@login_required
def mentorship_profile_manage(request):
    alumni = get_object_or_404(Alumni, user=request.user)
    profile, _ = MentorshipProfile.objects.get_or_create(alumni=alumni)
    if request.method == 'POST':
        form = MentorshipProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            alumni.is_available_for_mentoring = profile.is_available
            alumni.save(update_fields=['is_available_for_mentoring', 'updated_at'])
            messages.success(request, 'Mentorluk tercihleriniz güncellendi.')
            return redirect('career:mentorship_dashboard')
    else:
        form = MentorshipProfileForm(instance=profile)
    return render(request, 'career/mentorship_profile_form.html', {'form': form})


@login_required
@require_POST
def mentorship_request_create(request, mentor_id):
    ensure_interactive_account(request.user)
    if getattr(request.user.profile, 'user_type', '') != 'student':
        raise PermissionDenied
    mentor = get_object_or_404(MentorshipProfile.objects.select_related('alumni', 'alumni__user'), pk=mentor_id, is_available=True, alumni__user__is_active=True)
    if mentor.alumni.user_id == request.user.id:
        raise PermissionDenied
    if is_rate_limited(request, scope='mentorship-request', limit=5, window_seconds=86400):
        messages.error(request, 'Günlük mentorluk talebi limitine ulaştınız.')
        return redirect('career:mentor_list')
    month_start = timezone.localdate().replace(day=1)
    accepted_this_month = mentor.requests.filter(status='accepted', responded_at__date__gte=month_start).count()
    if accepted_this_month >= mentor.monthly_capacity:
        messages.error(request, 'Bu mentorun aylık kapasitesi şu anda dolu.')
        return redirect('career:mentor_list')
    form = MentorshipRequestForm(request.POST, mentor=mentor)
    if form.is_valid():
        try:
            with transaction.atomic():
                mentorship_request = form.save(commit=False)
                mentorship_request.student = request.user
                mentorship_request.mentor = mentor
                mentorship_request.save()
        except IntegrityError:
            messages.error(request, 'Bu mentorla zaten devam eden bir talebiniz var.')
        else:
            create_notification(recipient=mentor.alumni.user, actor=request.user, notification_type='mentorship_request', message=f'{request.user.get_full_name() or request.user.username} mentorluk talebi gönderdi.', target_url='/career/mentorship/')
            record_analytics_event(request, event_type='mentorship_request', target=mentor, succeeded=True)
            messages.success(request, 'Mentorluk talebiniz gönderildi.')
    else:
        messages.error(request, 'Mentorluk talebi alanlarını kontrol edin.')
    return redirect('career:mentorship_dashboard')


@login_required
def mentorship_dashboard(request):
    student_requests = request.user.mentorship_requests.select_related('mentor', 'mentor__alumni', 'topic')
    mentor_profile = MentorshipProfile.objects.filter(alumni__user=request.user).first()
    mentor_requests = mentor_profile.requests.select_related('student', 'student__profile', 'topic') if mentor_profile else MentorshipRequest.objects.none()
    return render(request, 'career/mentorship_dashboard.html', {
        'student_requests': student_requests,
        'mentor_requests': mentor_requests,
        'mentor_profile': mentor_profile,
        'response_form': MentorshipResponseForm(),
        'review_form': MentorshipReviewForm(),
    })


@login_required
@require_POST
def mentorship_request_respond(request, request_id, decision):
    mentorship_request = get_object_or_404(MentorshipRequest.objects.select_related('mentor__alumni', 'student'), pk=request_id, mentor__alumni__user=request.user)
    if mentorship_request.status != 'pending' or decision not in {'accepted', 'rejected'}:
        raise PermissionDenied
    form = MentorshipResponseForm(request.POST)
    if form.is_valid():
        mentorship_request.status = decision
        mentorship_request.mentor_response = form.cleaned_data['mentor_response']
        mentorship_request.responded_at = timezone.now()
        mentorship_request.save(update_fields=['status', 'mentor_response', 'responded_at', 'updated_at'])
        create_notification(recipient=mentorship_request.student, actor=request.user, notification_type='mentorship_request', message=f'Mentorluk talebin {mentorship_request.get_status_display().lower()}.', target_url='/career/mentorship/')
        messages.success(request, 'Talep güncellendi.')
    return redirect('career:mentorship_dashboard')


@login_required
@require_POST
def mentorship_request_complete(request, request_id):
    mentorship_request = get_object_or_404(MentorshipRequest.objects.select_related('mentor__alumni'), pk=request_id)
    if mentorship_request.status != 'accepted' or request.user.id not in {mentorship_request.student_id, mentorship_request.mentor.alumni.user_id}:
        raise PermissionDenied
    mentorship_request.status = 'completed'
    mentorship_request.completed_at = timezone.now()
    mentorship_request.save(update_fields=['status', 'completed_at', 'updated_at'])
    messages.success(request, 'Mentorluk süreci tamamlandı.')
    return redirect('career:mentorship_dashboard')


@login_required
@require_POST
def mentorship_review_create(request, request_id):
    mentorship_request = get_object_or_404(MentorshipRequest, pk=request_id, student=request.user, status='completed')
    form = MentorshipReviewForm(request.POST)
    if form.is_valid() and not MentorshipReview.objects.filter(mentorship_request=mentorship_request).exists():
        review = form.save(commit=False)
        review.mentorship_request = mentorship_request
        review.save()
        messages.success(request, 'Değerlendirmeniz kaydedildi.')
    return redirect('career:mentorship_dashboard')
