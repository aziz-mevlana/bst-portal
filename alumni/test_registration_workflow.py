from datetime import date

from django.contrib.auth.models import User
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from core.models import AuditLog, Notification

from .models import Alumni, AlumniRegistrationRequest, WorkExperience
from .services import approve_existing_registration, approve_new_registration, reject_registration


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='noreply@bst.test', EMAIL_USE_TLS=False, EMAIL_USE_SSL=False,
)
class AlumniRegistrationWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('alumni-admin', password='StrongPassword123!', is_staff=True)
        self.applicant = User.objects.create_user(
            'alumni-applicant', 'personal@example.com', 'StrongPassword123!', is_active=False,
            first_name='Ayşe', last_name='Mezun',
        )
        self.applicant.profile.user_type = 'alumni'
        self.applicant.profile.account_status = 'pending_review'
        self.applicant.profile.class_level = None
        self.applicant.profile.save()
        self.registration = AlumniRegistrationRequest.objects.create(
            user=self.applicant, full_name='Ayşe Mezun', graduation_year=2022,
            student_number='2019000123', email='personal@example.com',
        )

    def test_linking_existing_alumni_preserves_work_experience_and_copies_canonical_social_links(self):
        alumni = Alumni.objects.create(
            full_name='Ayşe Mezun', graduation_year=2022,
            linkedin_url='https://www.linkedin.com/in/ayse-mezun',
            github_url='https://github.com/ayse-mezun',
        )
        experience = WorkExperience.objects.create(
            person=alumni, company='BST', position='Geliştirici', start_date=date(2022, 1, 1),
            description='Mevcut kayıt korunmalı.',
        )
        with self.captureOnCommitCallbacks(execute=True):
            result = approve_existing_registration(
                registration_id=self.registration.pk, alumni_id=alumni.pk, reviewer=self.admin,
            )
        result.refresh_from_db()
        self.applicant.refresh_from_db()
        self.applicant.profile.refresh_from_db()
        self.registration.refresh_from_db()
        self.assertEqual(result.user, self.applicant)
        self.assertTrue(WorkExperience.objects.filter(pk=experience.pk, person=result).exists())
        self.assertEqual(self.applicant.profile.github_username, 'ayse-mezun')
        self.assertEqual(self.applicant.profile.linkedin_slug, 'ayse-mezun')
        self.assertTrue(self.applicant.is_active)
        self.assertEqual(self.registration.status, 'approved_linked')

    def test_existing_alumni_bound_to_another_account_cannot_be_reassigned(self):
        other = User.objects.create_user('already-linked')
        alumni = Alumni.objects.create(user=other, full_name='Bağlı Mezun')
        with self.assertRaises(ValidationError):
            approve_existing_registration(
                registration_id=self.registration.pk, alumni_id=alumni.pk, reviewer=self.admin,
            )

    def test_new_alumni_requires_second_confirmation(self):
        with self.assertRaises(ValidationError):
            approve_new_registration(
                registration_id=self.registration.pk, reviewer=self.admin, confirmed=False,
            )
        self.assertFalse(Alumni.objects.filter(user=self.applicant).exists())
        with self.captureOnCommitCallbacks(execute=True):
            alumni = approve_new_registration(
                registration_id=self.registration.pk, reviewer=self.admin, confirmed=True,
            )
        self.assertEqual(alumni.student_number, '2019000123')
        self.assertTrue(self.applicant.notifications.filter(notification_type='alumni_registration').exists())

    def test_rejection_requires_reason_and_description_and_produces_audit_notification_email(self):
        with self.assertRaises(ValidationError):
            reject_registration(
                registration_id=self.registration.pk, reviewer=self.admin,
                reason='', description='',
            )
        with self.captureOnCommitCallbacks(execute=True):
            reject_registration(
                registration_id=self.registration.pk, reviewer=self.admin,
                reason='other', description='Bilgiler mevcut mezun kayıtlarıyla doğrulanamadı.',
            )
        self.registration.refresh_from_db()
        self.assertEqual(self.registration.status, 'rejected')
        self.assertTrue(Notification.objects.filter(recipient=self.applicant).exists())
        self.assertTrue(AuditLog.objects.filter(action='alumni.registration_rejected').exists())
        self.assertEqual(len(mail.outbox), 1)
