from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import bootstrap_bst_authority_group

from .models import CollaborationRequest


class CollaborationFirstReviewTests(TestCase):
    def setUp(self):
        bootstrap_bst_authority_group()
        self.authority = User.objects.create_user('collab-authority', password='StrongPassword123!')
        self.authority.profile.user_type = 'staff_student'
        self.authority.profile.class_level = '3'
        self.authority.profile.save()
        self.item = CollaborationRequest.objects.create(
            contact_name='Yetkili Kişi', organization='BST Şirket', job_title='Ar-Ge',
            email='contact@example.com', request_type='other', title='İş birliği',
            description='Birlikte teknoloji etkinliği düzenlemek istiyoruz.',
            consent_accepted=True, consent_at=timezone.now(), email_verified_at=timezone.now(),
            status='pending_review', publication_channel='internal',
        )
        self.payload = {
            'action': 'first_review', 'normalized_title': 'İş birliği',
            'normalized_description': 'Düzenlenmiş iş birliği açıklaması.',
            'publication_channel': 'internal', 'admin_note': 'İlk inceleme tamamlandı.',
        }

    def test_authority_can_open_dashboard_embedded_management_and_complete_first_review(self):
        self.client.force_login(self.authority)
        listing = self.client.get(reverse('career:collaboration_manage'))
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, 'dashboard-shell')
        response = self.client.post(
            reverse('career:collaboration_review', args=[self.item.pk]), self.payload,
        )
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, 'approved')
        self.assertEqual(self.item.reviewed_by, self.authority)

    def test_authority_cannot_publish_even_with_direct_endpoint_post(self):
        self.client.force_login(self.authority)
        response = self.client.post(
            reverse('career:collaboration_review', args=[self.item.pk]),
            {**self.payload, 'action': 'publish'},
        )
        self.assertEqual(response.status_code, 403)
        self.item.refresh_from_db()
        self.assertNotEqual(self.item.status, 'published')
