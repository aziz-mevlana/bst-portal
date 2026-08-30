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
