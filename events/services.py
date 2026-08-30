from django.core.exceptions import ValidationError
from django.db import transaction

from core.notifications import create_notification

from .models import Event, EventRegistration


@transaction.atomic
def register_for_event(*, event_id, user):
    event = Event.objects.select_for_update().get(pk=event_id, is_active=True)
    if not event.registration_is_open:
        raise ValidationError('Etkinlik kayıtları şu anda açık değil.')
    registration = EventRegistration.objects.select_for_update().filter(event=event, user=user).first()
    if registration and registration.status != 'cancelled':
        return registration, False
    full = event.capacity is not None and event.registrations.filter(status__in=['registered', 'attended']).count() >= event.capacity
    if full and not event.waitlist_enabled:
        raise ValidationError('Etkinlik kontenjanı doldu.')
    status = 'waitlisted' if full else 'registered'
    if registration:
        registration.status = status
        registration.checked_in_at = None
        registration.save(update_fields=['status', 'checked_in_at', 'updated_at'])
    else:
        registration = EventRegistration.objects.create(event=event, user=user, status=status)
    return registration, True


@transaction.atomic
def cancel_event_registration(*, registration_id, user):
    registration = EventRegistration.objects.select_for_update().select_related('event').get(pk=registration_id, user=user)
    previous_status = registration.status
    if previous_status not in {'registered', 'waitlisted'}:
        raise ValidationError('Bu etkinlik kaydı iptal edilemez.')
    registration.status = 'cancelled'
    registration.save(update_fields=['status', 'updated_at'])
    promoted = None
    if previous_status == 'registered':
        promoted = registration.event.registrations.select_for_update().filter(status='waitlisted').select_related('user').first()
        if promoted:
            promoted.status = 'registered'
            promoted.save(update_fields=['status', 'updated_at'])
            create_notification(
                recipient=promoted.user,
                notification_type='event',
                message=f'“{registration.event.title}” etkinliğinde bekleme listesinden kayda geçtiniz.',
                target_url=f'/events/{registration.event_id}/',
            )
    return registration, promoted
