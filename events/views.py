from datetime import timezone as dt_timezone

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from accounts.permissions import ensure_full_participation_account

from core.audit import record_audit_event
from core.analytics import record_analytics_event
from accounts.policies import can_manage_events, is_admin, is_teacher, role_of

from .forms import EventFeedbackForm, EventForm
from .models import Event, EventRegistration
from .services import cancel_event_registration, register_for_event

PAGE_SIZE = 12

def _user_can_manage_event(user, event=None, action='change'):
    if not user.is_authenticated:
        return False
    if is_admin(user) or is_teacher(user):
        return True
    if role_of(user) == 'staff_student' and can_manage_events(user, action):
        return True
    if event and event.created_by_id == user.id:
        return True
    return False

def event_list(request):
    show_create_card = can_manage_events(request.user, 'add')
    page_size = PAGE_SIZE - 1 if show_create_card else PAGE_SIZE
    events = Event.objects.filter(is_active=True)[:page_size]
    total_count = Event.objects.filter(is_active=True).count()
    has_more = total_count > page_size
    return render(request, 'events/event_list.html', {
        'events': events,
        'has_more': has_more,
        'next_offset': page_size,
        'total_count': total_count
    })

def event_load_more(request):
    try:
        offset = max(0, int(request.GET.get('offset', 0)))
    except (TypeError, ValueError):
        offset = 0
    limit = PAGE_SIZE
    
    events = Event.objects.filter(is_active=True)[offset:offset + limit]
    total_count = Event.objects.filter(is_active=True).count()
    has_more = offset + limit < total_count
    
    html = render_to_string('events/partials/event_item.html', {'events': events})
    
    return JsonResponse({
        'items': html,
        'has_more': has_more,
        'next_offset': offset + limit
    })

def event_detail(request, event_id):
    event = get_object_or_404(Event, id=event_id, is_active=True)
    registration = None
    if request.user.is_authenticated:
        registration = EventRegistration.objects.filter(event=event, user=request.user).first()
    return render(request, 'events/event_detail.html', {
        'event': event,
        'registration': registration,
        'now': timezone.now(),
        'can_manage_event': _user_can_manage_event(request.user, event),
        'feedback_form': EventFeedbackForm(),
    })

@login_required
def create_event(request):
    if not _user_can_manage_event(request.user, action='add'):
        return redirect('events:event_list')
    
    if request.method == 'POST':
        form = EventForm(request.POST, request.FILES)
        if form.is_valid():
            event = form.save(commit=False)
            event.created_by = request.user
            event.save()
            messages.success(request, 'Etkinlik başarıyla oluşturuldu.')
            return redirect('dashboard:events')
        messages.error(request, 'Etkinlik kaydedilemedi. Tarihleri ve zorunlu alanları kontrol edin.')
    else:
        form = EventForm()
    return render(request, 'events/create_event.html', {
        'event_obj': form.instance,
        'form': form,
        'submit_label': 'Oluştur',
        'page_title': 'Yeni Etkinlik Oluştur',
        'page_description': 'Yetkili kullanıcılar etkinlikleri buradan ekleyebilir.',
        'is_edit': False,
        'panel_mode': True,
    })

@login_required
def edit_event(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    if not _user_can_manage_event(request.user, event, action='change'):
        messages.error(request, 'Bu etkinliği düzenleme yetkiniz yok.')
        return redirect('events:event_detail', event_id=event.id)

    if request.method == 'POST':
        form = EventForm(request.POST, request.FILES, instance=event)
        if form.is_valid():
            event = form.save()
            messages.success(request, 'Etkinlik başarıyla güncellendi.')
            return redirect('dashboard:events')
        messages.error(request, 'Etkinlik güncellenemedi. Tarihleri ve zorunlu alanları kontrol edin.')
    else:
        form = EventForm(instance=event)

    return render(request, 'events/create_event.html', {
        'event_obj': event,
        'form': form,
        'submit_label': 'Güncelle',
        'page_title': 'Etkinliği Düzenle',
        'page_description': 'Etkinlik bilgilerini güncelleyin ve kaydedin.',
        'is_edit': True,
        'panel_mode': True,
    })

@login_required
@require_POST
def delete_event(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    if not _user_can_manage_event(request.user, event, action='delete'):
        messages.error(request, 'Bu etkinliği silme yetkiniz yok.')
        return redirect('events:event_detail', event_id=event.id)

    event.delete()
    messages.success(request, 'Etkinlik başarıyla silindi.')
    return redirect('dashboard:events')


@login_required
@require_POST
def event_register(request, event_id):
    ensure_full_participation_account(request.user)
    try:
        registration, created = register_for_event(event_id=event_id, user=request.user)
    except (Event.DoesNotExist, ValidationError) as exc:
        messages.error(request, str(exc))
    else:
        if not created:
            messages.info(request, 'Bu etkinlik için zaten bir kaydınız var.')
        elif registration.status == 'waitlisted':
            messages.success(request, 'Kontenjan dolu; bekleme listesine eklendiniz.')
        else:
            messages.success(request, 'Etkinlik kaydınız oluşturuldu.')
        if created:
            record_analytics_event(request, event_type='event_registration', target=registration.event, succeeded=True, metadata={'status': registration.status})
    return redirect('events:event_detail', event_id=event_id)


@login_required
@require_POST
def event_registration_cancel(request, registration_id):
    registration = get_object_or_404(EventRegistration, pk=registration_id, user=request.user)
    event_id = registration.event_id
    try:
        cancel_event_registration(registration_id=registration.pk, user=request.user)
    except ValidationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, 'Etkinlik kaydınız iptal edildi.')
    return redirect('events:event_detail', event_id=event_id)


@login_required
def event_registration_qr(request, registration_id):
    registration = get_object_or_404(
        EventRegistration.objects.select_related('event'),
        pk=registration_id,
        user=request.user,
        status__in=['registered', 'attended'],
    )
    import qrcode
    checkin_url = request.build_absolute_uri(
        reverse('events:event_checkin', kwargs={'token': registration.checkin_token})
    )
    image = qrcode.make(checkin_url)
    response = HttpResponse(content_type='image/png')
    image.save(response, 'PNG')
    return response


@login_required
def event_checkin(request, token):
    registration = get_object_or_404(
        EventRegistration.objects.select_related('event', 'user', 'user__profile'),
        checkin_token=token,
    )
    if not _user_can_manage_event(request.user, registration.event):
        raise PermissionDenied
    if request.method == 'POST':
        if registration.status == 'attended':
            messages.info(request, 'Bu katılımcının yoklaması daha önce alındı.')
        elif registration.status != 'registered':
            messages.error(request, 'Bu kayıt yoklama için uygun değil.')
        else:
            registration.status = 'attended'
            registration.checked_in_at = timezone.now()
            registration.certificate_eligible = registration.event.certificate_enabled
            registration.save(update_fields=['status', 'checked_in_at', 'certificate_eligible', 'updated_at'])
            record_audit_event(actor=request.user, action='event.checkin', target=registration, request=request)
            messages.success(request, 'Katılımcı yoklaması alındı.')
        return redirect('events:event_participants', event_id=registration.event_id)
    return render(request, 'events/checkin_confirm.html', {'registration': registration})


@login_required
def event_participants(request, event_id):
    event = get_object_or_404(Event, pk=event_id)
    if not _user_can_manage_event(request.user, event):
        raise PermissionDenied
    registrations = event.registrations.select_related('user', 'user__profile')
    return render(request, 'events/participants.html', {
        'event': event,
        'registrations': registrations,
        'attended_count': registrations.filter(status='attended').count(),
    })


@login_required
@require_POST
def event_feedback(request, registration_id):
    registration = get_object_or_404(EventRegistration, pk=registration_id, user=request.user, status='attended')
    form = EventFeedbackForm(request.POST)
    if form.is_valid():
        registration.feedback_rating = form.cleaned_data['rating']
        registration.feedback_comment = form.cleaned_data['comment']
        registration.feedback_at = timezone.now()
        registration.save(update_fields=['feedback_rating', 'feedback_comment', 'feedback_at', 'updated_at'])
        messages.success(request, 'Etkinlik değerlendirmeniz kaydedildi.')
    return redirect('events:event_detail', event_id=registration.event_id)


def event_calendar(request, event_id):
    event = get_object_or_404(Event, pk=event_id, is_active=True)

    def escape(value):
        return str(value).replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')

    start = event.start_date.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    end = event.end_date.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    stamp = timezone.now().astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    detail_url = request.build_absolute_uri(reverse('events:event_detail', args=[event.pk]))
    content = '\r\n'.join([
        'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//BST Portal//Events//TR',
        'BEGIN:VEVENT', f'UID:event-{event.pk}@bst-portal', f'DTSTAMP:{stamp}',
        f'DTSTART:{start}', f'DTEND:{end}', f'SUMMARY:{escape(event.title)}',
        f'DESCRIPTION:{escape(event.description)}', f'LOCATION:{escape(event.location)}',
        f'URL:{detail_url}', 'END:VEVENT', 'END:VCALENDAR', '',
    ])
    response = HttpResponse(content, content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="bst-event-{event.pk}.ics"'
    return response
