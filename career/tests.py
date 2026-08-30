from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.test import override_settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from alumni.models import Alumni
from core.models import AuditLog, Notification
from accounts.models import EmailVerification
from projects.models import ProjectRequest, ProjectType

from .collaboration_service import publish_collaboration
from .forms import CollaborationRequestForm, OpportunityForm
from .models import CollaborationRequest, MentorshipProfile, MentorshipRequest, Opportunity


def make_user(username, user_type):
    user = User.objects.create_user(username, f'{username}@example.com', 'StrongPassword123!')
    user.profile.user_type = user_type
    user.profile.save(update_fields=['user_type'])
    return user


class OpportunityTests(TestCase):
    def setUp(self):
        self.alumni_user = make_user('alumni-publisher', 'alumni')
        self.student = make_user('career-student', 'student')

    def create_opportunity(self, **overrides):
        values = {
            'title': 'Backend Stajyeri',
            'opportunity_type': 'internship',
            'organization': 'BST Teknoloji',
            'description': 'Django ekibine stajyer aranıyor.',
            'work_mode': 'hybrid',
            'application_url': 'https://example.com/apply',
            'contact_method': 'url',
            'created_by': self.alumni_user,
        }
        values.update(overrides)
        return Opportunity.objects.create(**values)

    def test_public_list_only_shows_approved_open_opportunities(self):
        approved = self.create_opportunity(approval_status='approved')
        pending = self.create_opportunity(title='Onay bekleyen', approval_status='pending')
        expired = self.create_opportunity(title='Süresi dolan', approval_status='approved', deadline=timezone.localdate() - timedelta(days=1))
        response = self.client.get(reverse('career:opportunity_list'))
        self.assertContains(response, approved.title)
        self.assertNotContains(response, pending.title)
        self.assertNotContains(response, expired.title)

    def test_student_cannot_create_opportunity(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('career:opportunity_create')).status_code, 403)

    def test_alumni_created_opportunity_requires_moderation(self):
        self.client.force_login(self.alumni_user)
        response = self.client.post(reverse('career:opportunity_create'), {
            'title': 'Yeni İlan', 'opportunity_type': 'full_time', 'organization': 'Kurum',
            'description': 'Açıklama', 'work_mode': 'remote',
            'contact_method': 'email', 'contact_email': 'ik@example.com',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Opportunity.objects.get(title='Yeni İlan').approval_status, 'pending')

    def test_opportunity_form_uses_clear_turkish_labels_and_rejects_past_deadline(self):
        form = OpportunityForm()
        self.assertEqual(form.fields['opportunity_type'].label, 'İlan Türü')
        self.assertEqual(form.fields['work_mode'].label, 'Çalışma Şekli')
        self.assertEqual(form.fields['contact_method'].label, 'Başvuru Yöntemi')
        invalid = OpportunityForm(data={
            'title': 'Eski ilan', 'opportunity_type': 'internship', 'organization': 'BST',
            'description': 'Açıklama', 'work_mode': 'remote', 'contact_method': 'email',
            'contact_email': 'ik@example.com',
            'deadline': (timezone.localdate() - timedelta(days=1)).isoformat(),
        })
        self.assertFalse(invalid.is_valid())
        self.assertIn('deadline', invalid.errors)

    def test_admin_can_manage_and_delete_any_opportunity(self):
        pending = self.create_opportunity(approval_status='pending')
        admin = User.objects.create_user(
            'career-admin', 'career-admin@example.com', 'StrongPassword123!', is_staff=True
        )
        self.client.force_login(admin)
        response = self.client.get(reverse('career:opportunity_list'), {'scope': 'all'})
        self.assertContains(response, pending.title)
        delete_url = reverse('career:opportunity_delete', args=[pending.pk])
        self.assertEqual(self.client.get(delete_url).status_code, 405)
        self.client.post(delete_url)
        self.assertTrue(Opportunity.objects.filter(pk=pending.pk).exists())
        self.client.post(delete_url, {'confirm_delete': 'yes'})
        self.assertFalse(Opportunity.objects.filter(pk=pending.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action='opportunity.deleted').exists())

    def test_creator_edit_returns_approved_opportunity_to_pending_review(self):
        opportunity = self.create_opportunity(approval_status='approved')
        self.client.force_login(self.alumni_user)
        response = self.client.post(reverse('career:opportunity_edit', args=[opportunity.pk]), {
            'title': 'Güncellenen Backend İlanı', 'opportunity_type': 'internship',
            'organization': 'BST Teknoloji', 'description': 'Güncel açıklama',
            'work_mode': 'hybrid', 'contact_method': 'url',
            'application_url': 'https://example.com/new-apply',
        })
        self.assertEqual(response.status_code, 302)
        opportunity.refresh_from_db()
        self.assertEqual(opportunity.title, 'Güncellenen Backend İlanı')
        self.assertEqual(opportunity.approval_status, 'pending')

    def test_bst_authority_without_career_permission_cannot_approve(self):
        pending = self.create_opportunity(approval_status='pending')
        authority = make_user('career-authority', 'staff_student')
        self.assertFalse(authority.has_perm('career.change_opportunity'))
        self.client.force_login(authority)

        response = self.client.post(reverse('career:opportunity_approve', args=[pending.pk]))

        self.assertEqual(response.status_code, 403)
        pending.refresh_from_db()
        self.assertEqual(pending.approval_status, 'pending')


class MentorshipFlowTests(TestCase):
    def setUp(self):
        self.student = make_user('mentor-student', 'student')
        self.mentor_user = make_user('mentor-alumni', 'alumni')
        alumni = Alumni.objects.create(
            user=self.mentor_user,
            full_name='Deneyimli Mezun',
            current_position='Yazılım Mühendisi',
            company='BST Teknoloji',
            is_show_in_alumni_list=True,
        )
        self.mentor = MentorshipProfile.objects.create(
            alumni=alumni,
            is_available=True,
            preferred_contact_method='email',
        )

    def test_contact_is_only_shared_after_acceptance(self):
        self.client.force_login(self.student)
        mentor_list = self.client.get(reverse('career:mentor_list'))
        self.assertContains(mentor_list, 'Deneyimli Mezun')
        self.assertNotContains(mentor_list, self.mentor_user.email)
        response = self.client.post(reverse('career:mentorship_request_create', args=[self.mentor.pk]), {
            'goal': 'Kariyer planımı netleştirmek',
            'message': 'Backend alanında yol haritası arıyorum.',
        })
        self.assertRedirects(response, reverse('career:mentorship_dashboard'))
        mentorship_request = MentorshipRequest.objects.get(student=self.student)
        self.assertTrue(Notification.objects.filter(recipient=self.mentor_user).exists())
        dashboard = self.client.get(reverse('career:mentorship_dashboard'))
        self.assertNotContains(dashboard, self.mentor_user.email)

        self.client.force_login(self.mentor_user)
        accept_url = reverse('career:mentorship_request_respond', args=[mentorship_request.pk, 'accepted'])
        self.assertEqual(self.client.get(accept_url).status_code, 405)
        self.client.post(accept_url, {'mentor_response': 'Memnuniyetle yardımcı olurum.'})
        mentorship_request.refresh_from_db()
        self.assertEqual(mentorship_request.status, 'accepted')

        self.client.force_login(self.student)
        dashboard = self.client.get(reverse('career:mentorship_dashboard'))
        self.assertContains(dashboard, self.mentor_user.email)

    def test_duplicate_active_request_is_prevented(self):
        MentorshipRequest.objects.create(student=self.student, mentor=self.mentor, goal='İlk hedef', message='İlk mesaj')
        self.client.force_login(self.student)
        self.client.post(reverse('career:mentorship_request_create', args=[self.mentor.pk]), {
            'goal': 'İkinci hedef', 'message': 'İkinci mesaj',
        })
        self.assertEqual(MentorshipRequest.objects.filter(student=self.student, mentor=self.mentor).count(), 1)


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='noreply@bstakademi.test',
    EMAIL_USE_TLS=False,
    EMAIL_USE_SSL=False,
)
class CollaborationFlowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('collab-admin', password='StrongPassword123!', is_staff=True)
        self.teacher = make_user('collab-teacher', 'teacher')
        self.project_type = ProjectType.objects.get(code='RESEARCH')
        self.form_data = {
            'contact_name': 'Ayşe Yetkili', 'organization': 'ABC Teknoloji',
            'job_title': 'Ar-Ge Müdürü', 'email': 'ayse@example.com',
            'request_type': 'project', 'title': 'Veri analizi projesi',
            'description': 'Öğrencilerle birlikte veri analizi projesi geliştirmek istiyoruz.',
            'preferred_contact': 'email', 'consent_accepted': 'on',
        }

    def _verified_item(self, request_type='project'):
        return CollaborationRequest.objects.create(
            tracking_number=f'BST-TEST-{CollaborationRequest.objects.count() + 1}',
            contact_name='Ayşe Yetkili', organization='ABC Teknoloji', job_title='Müdür',
            email='ayse@example.com', request_type=request_type, title='Talep',
            description='Açıklama', preferred_contact='email', consent_accepted=True,
            consent_at=timezone.now(), email_verified_at=timezone.now(), status='pending_review',
            assigned_teacher=self.teacher, project_type=self.project_type,
        )

    def test_public_form_uses_resilient_form_layout(self):
        response = self.client.get(reverse('career:collaboration_create'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="collaboration-form"')
        self.assertContains(response, 'class="collaboration-form-grid"')
        self.assertContains(response, 'class="collaboration-submit"')

    def test_collaboration_requires_real_choices_and_has_placeholders(self):
        form = CollaborationRequestForm(data={**self.form_data, 'request_type': '', 'preferred_contact': ''})

        self.assertFalse(form.is_valid())
        self.assertIn('request_type', form.errors)
        self.assertIn('preferred_contact', form.errors)
        self.assertTrue(form.fields['request_type'].widget.attrs['required'])
        for field_name in ('contact_name', 'organization', 'job_title', 'email', 'title', 'description'):
            self.assertTrue(form.fields[field_name].widget.attrs.get('placeholder'))

    def test_external_visitor_can_submit_and_verify_request(self):
        response = self.client.post(reverse('career:collaboration_create'), self.form_data)
        self.assertRedirects(response, reverse('career:collaboration_verify'))
        item = CollaborationRequest.objects.get()
        self.assertEqual(item.status, 'pending_email')
        verification = EmailVerification.objects.get(email=item.email)
        self.assertEqual(verification.code, '')
        code = mail.outbox[0].body.split('Doğrulama kodunuz: ', 1)[1].splitlines()[0]
        response = self.client.post(reverse('career:collaboration_verify'), {'code': code})
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.status, 'pending_review')
        self.assertIsNotNone(item.email_verified_at)

    def test_unverified_request_cannot_be_published(self):
        item = self._verified_item()
        item.email_verified_at = None
        item.save(update_fields=['email_verified_at'])
        with self.assertRaises(ValidationError):
            publish_collaboration(item.pk, self.admin)

    def test_only_real_admin_can_open_management(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse('career:collaboration_manage')).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.get(reverse('career:collaboration_manage'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dashboard-shell')
        self.assertContains(response, 'İş birliği talepleri')

    def test_project_conversion_is_idempotent(self):
        item = self._verified_item()
        first = publish_collaboration(item.pk, self.admin)
        second = publish_collaboration(item.pk, self.admin)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ProjectRequest.objects.filter(source_collaboration=item).count(), 1)
        self.assertEqual(first.teacher, self.teacher)

    def test_recruitment_becomes_career_opportunity_not_project_request(self):
        item = self._verified_item(request_type='recruitment')
        result = publish_collaboration(item.pk, self.admin)
        self.assertIsInstance(result, Opportunity)
        item.refresh_from_db()
        self.assertIsNone(item.project_request)
        self.assertEqual(item.opportunity, result)
