from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import CommunicationPreference
from .models import Notification
from .notifications import create_notification


class NotificationModernizationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('notification-user', password='StrongPassword123!')

    def test_dedupe_key_prevents_duplicate_event(self):
        first = create_notification(
            recipient=self.user, notification_type='system', title='Görev', message='İlk',
            target_url='/projects/', dedupe_key='same-event',
        )
        second = create_notification(
            recipient=self.user, notification_type='system', title='Görev', message='İkinci',
            target_url='/projects/', dedupe_key='same-event',
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Notification.objects.filter(recipient=self.user).count(), 1)

    def test_preference_suppresses_normal_notification_but_force_bypasses_it(self):
        preferences, _ = CommunicationPreference.objects.get_or_create(user=self.user)
        preferences.platform_notifications = False
        preferences.save(update_fields=['platform_notifications'])
        self.assertIsNone(create_notification(
            recipient=self.user, notification_type='system', message='İsteğe bağlı',
        ))
        forced = create_notification(
            recipient=self.user, notification_type='moderation', message='Zorunlu güvenlik bildirimi',
            force=True,
        )
        self.assertIsNotNone(forced)

    def test_header_has_accessible_button_dropdown_and_unread_badge(self):
        create_notification(
            recipient=self.user, notification_type='system', title='Yeni bildirim',
            message='İçerik', target_url='/projects/',
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse('projects:project_list'))
        self.assertContains(response, 'id="notification-button"')
        self.assertContains(response, 'aria-expanded="false"')
        self.assertContains(response, 'id="notification-menu"')
        self.assertContains(response, 'id="notification-menu" class="notification-menu" role="menu" hidden')
        self.assertContains(response, 'id="notification-badge"')
        self.assertContains(response, 'id="mobile-notification-link"')
        self.assertContains(response, 'js/header.js?v=20260820.1')

    def test_mark_all_read_supports_json_progressive_enhancement(self):
        Notification.objects.bulk_create([
            Notification(recipient=self.user, notification_type='system', message='Bir'),
            Notification(recipient=self.user, notification_type='system', message='İki'),
        ])
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('core:notification_mark_all_read'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['updated'], 2)
        self.assertFalse(self.user.notifications.filter(read_at__isnull=True).exists())
