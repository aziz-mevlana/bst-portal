from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import EventForm
from .models import Event, EventRegistration
from .services import cancel_event_registration, register_for_event


class EventValidationTests(TestCase):
    def test_end_date_must_be_after_start_date(self):
        form = EventForm(data={
            'title': 'Test etkinliği',
            'description': 'Açıklama',
            'event_type': 'seminar',
            'location': 'Kampüs',
            'start_date': '2026-07-15 12:00:00',
            'end_date': '2026-07-15 11:00:00',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('end_date', form.errors)


class EventRegistrationTests(TestCase):
    def setUp(self):
        self.organizer = User.objects.create_user('organizer', password='StrongPassword123!')
        self.organizer.profile.user_type = 'teacher'
        self.organizer.profile.save(update_fields=['user_type'])
        self.first = User.objects.create_user('first-attendee', password='StrongPassword123!')
        self.second = User.objects.create_user('second-attendee', password='StrongPassword123!')
        self.event = Event.objects.create(
            title='Kontenjanlı Atölye',
            description='Uygulamalı etkinlik',
            event_type='workshop',
            location='Kampüs',
            start_date=timezone.now() + timedelta(days=5),
            end_date=timezone.now() + timedelta(days=5, hours=2),
            created_by=self.organizer,
            allow_registration=True,
            capacity=1,
            waitlist_enabled=True,
            certificate_enabled=True,
        )

    def test_capacity_waitlist_and_automatic_promotion(self):
        first, created = register_for_event(event_id=self.event.pk, user=self.first)
        second, _ = register_for_event(event_id=self.event.pk, user=self.second)
        self.assertTrue(created)
        self.assertEqual(first.status, 'registered')
        self.assertEqual(second.status, 'waitlisted')
        cancel_event_registration(registration_id=first.pk, user=self.first)
        second.refresh_from_db()
        self.assertEqual(second.status, 'registered')
        self.assertTrue(self.second.notifications.filter(notification_type='event').exists())

    def test_secure_checkin_is_manager_only_and_single_use(self):
        registration, _ = register_for_event(event_id=self.event.pk, user=self.first)
        self.assertGreaterEqual(len(registration.checkin_token), 40)
        url = reverse('events:event_checkin', args=[registration.checkin_token])
        self.client.force_login(self.second)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.organizer)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url)
        registration.refresh_from_db()
        self.assertEqual(registration.status, 'attended')
        self.assertTrue(registration.certificate_eligible)
        checked_at = registration.checked_in_at
        self.client.post(url)
        registration.refresh_from_db()
        self.assertEqual(registration.checked_in_at, checked_at)

    def test_owner_can_download_qr_and_calendar(self):
        registration, _ = register_for_event(event_id=self.event.pk, user=self.first)
        self.client.force_login(self.first)
        qr = self.client.get(reverse('events:event_registration_qr', args=[registration.pk]))
        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr['Content-Type'], 'image/png')
        calendar = self.client.get(reverse('events:event_calendar', args=[self.event.pk]))
        self.assertEqual(calendar.status_code, 200)
        self.assertContains(calendar, 'BEGIN:VCALENDAR')

    def test_registration_mutations_require_post(self):
        self.client.force_login(self.first)
        self.assertEqual(self.client.get(reverse('events:event_register', args=[self.event.pk])).status_code, 405)

    def test_bst_authority_event_access_depends_on_assigned_permission(self):
        authority = User.objects.create_user('event-authority', password='StrongPassword123!')
        authority.profile.user_type = 'staff_student'
        authority.profile.save(update_fields=['user_type'])
        self.client.force_login(authority)
        self.assertEqual(self.client.get(reverse('dashboard:events')).status_code, 200)

        authority_group = authority.groups.get(name='BST Yetkilisi')
        authority_group.permissions.remove(*authority_group.permissions.filter(content_type__app_label='events'))
        authority = User.objects.get(pk=authority.pk)
        self.client.force_login(authority)
        self.assertEqual(self.client.get(reverse('dashboard:events')).status_code, 403)
        self.client.post(reverse('events:delete_event', args=[self.event.pk]))
        self.assertTrue(Event.objects.filter(pk=self.event.pk).exists())
