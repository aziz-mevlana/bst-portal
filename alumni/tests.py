from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Alumni


class AlumniListTests(TestCase):
    def setUp(self):
        viewer = User.objects.create_user('viewer', 'viewer@example.com', 'StrongPassword123!')
        self.client.force_login(viewer)
        Alumni.objects.create(
            full_name='<script>alert(1)</script>',
            current_position='Geliştirici',
            company='BST',
            user=None,
        )

    def test_unmatched_alumni_renders_safely(self):
        response = self.client.get(reverse('alumni:alumni_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')

    def test_load_more_requires_authentication(self):
        self.client.logout()
        response = self.client.get(reverse('alumni:load_more_alumni'))
        self.assertEqual(response.status_code, 302)


class AlumniAuthorizationTests(TestCase):
    def setUp(self):
        self.viewer = User.objects.create_user('alumni-viewer', 'viewer2@example.com', 'StrongPassword123!')
        self.hidden_user = User.objects.create_user('hidden-alumni', 'hidden@example.com', 'StrongPassword123!')
        self.hidden_user.profile.user_type = 'alumni'
        self.hidden_user.profile.save(update_fields=['user_type'])
        self.hidden = Alumni.objects.create(
            user=self.hidden_user,
            full_name='Gizli Mezun',
            is_show_in_alumni_list=False,
        )

    def test_hidden_alumni_is_not_available_by_username_or_id(self):
        self.client.force_login(self.viewer)
        self.assertEqual(
            self.client.get(reverse('alumni:alumni_detail', args=[self.hidden_user.username])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse('alumni:alumni_detail_by_id', args=[self.hidden.pk])).status_code,
            404,
        )

    def test_student_cannot_create_alumni_profile_through_hidden_endpoint(self):
        self.client.force_login(self.viewer)
        response = self.client.post(reverse('alumni:alumni_profile_edit'), {
            'graduation_year': '2025',
            'current_position': 'Sahte Mezun',
            'is_show_in_alumni_list': 'on',
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Alumni.objects.filter(user=self.viewer).exists())
