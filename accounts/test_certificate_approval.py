from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from core.models import AuditLog, Notification

from .models import PortfolioCertificate


class CertificateApprovalTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user('certificate-student', password='password')
        self.student.profile.user_type = 'student'
        self.student.profile.class_level = '4'
        self.student.profile.save()
        self.other = User.objects.create_user('certificate-other', password='password')
        self.admin = User.objects.create_superuser('certificate-admin', 'admin@example.test', 'password')
        self.certificate = PortfolioCertificate.objects.create(profile=self.student.profile,
            title='Gerçek Sertifika Adı', issuer='Üniversite',
            credential_url='https://certs.example.edu/verify/123')
        self.portfolio_url = reverse('portal:portfolio_detail', args=[self.student.profile.public_slug])

    def test_pending_is_private_approved_is_public_and_forged_redirect_is_ignored(self):
        warning = reverse('portal:portfolio_certificate_warning',
                          args=[self.student.profile.public_slug, self.certificate.pk])
        continuation = reverse('portal:portfolio_certificate_continue',
                               args=[self.student.profile.public_slug, self.certificate.pk])
        self.assertNotContains(self.client.get(self.portfolio_url), 'Gerçek Sertifika Adı')
        self.assertEqual(self.client.get(warning).status_code, 404)
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(reverse('accounts:portfolio_certificate_review', args=[self.certificate.pk]),
                                          {'decision': 'approve'}).status_code, 404)
        self.client.force_login(self.admin)
        self.client.post(reverse('accounts:portfolio_certificate_review', args=[self.certificate.pk]),
                         {'decision': 'approve'})
        self.certificate.refresh_from_db()
        self.assertEqual(self.certificate.verification_status, 'APPROVED')
        self.client.logout()
        self.assertContains(self.client.get(self.portfolio_url), 'Gerçek Sertifika Adı')
        self.assertContains(self.client.get(warning), 'Gerçek Sertifika Adı')
        response = self.client.get(continuation, {'next': 'https://attacker.example/'})
        self.assertEqual(response['Location'], self.certificate.credential_url)

    def test_reject_requires_reason_and_edit_resets_approval(self):
        review_url = reverse('accounts:portfolio_certificate_review', args=[self.certificate.pk])
        self.client.force_login(self.admin)
        self.client.post(review_url, {'decision': 'reject'})
        self.certificate.refresh_from_db()
        self.assertEqual(self.certificate.verification_status, 'PENDING')
        self.client.post(review_url, {'decision': 'approve'})
        self.certificate.refresh_from_db()
        self.assertEqual(self.certificate.verification_status, 'APPROVED')
        self.client.force_login(self.student)
        self.client.post(reverse('accounts:portfolio_certificate_edit', args=[self.certificate.pk]), {
            'title': 'Gerçek Sertifika Adı', 'issuer': 'Üniversite',
            'credential_url': 'https://youtube.com/watch?v=123',
            'credential_id': '', 'is_public': 'on',
        })
        self.certificate.refresh_from_db()
        self.assertEqual(self.certificate.verification_status, 'PENDING')
        self.assertIsNone(self.certificate.reviewed_by)
        self.client.logout()
        self.assertNotContains(self.client.get(self.portfolio_url), 'Gerçek Sertifika Adı')

    def test_unchanged_edit_keeps_approval_and_forged_review_fields_are_ignored(self):
        review_url = reverse('accounts:portfolio_certificate_review', args=[self.certificate.pk])
        self.client.force_login(self.admin)
        self.client.post(review_url, {'decision': 'approve'})
        notices = Notification.objects.filter(recipient=self.student).count()
        self.assertEqual(self.client.post(review_url, {'decision': 'approve'}).status_code, 404)
        self.assertEqual(Notification.objects.filter(recipient=self.student).count(), notices)
        self.client.force_login(self.student)
        edit_url = reverse('accounts:portfolio_certificate_edit', args=[self.certificate.pk])
        unchanged = {'title': self.certificate.title, 'issuer': self.certificate.issuer,
            'credential_url': self.certificate.credential_url, 'credential_id': '',
            'is_public': 'on', 'verification_status': 'APPROVED',
            'reviewed_by': str(self.student.pk)}
        self.client.post(edit_url, unchanged)
        self.certificate.refresh_from_db()
        self.assertEqual(self.certificate.verification_status, 'APPROVED')
        self.assertEqual(self.certificate.reviewed_by_id, self.admin.pk)
        self.client.post(edit_url, {**unchanged, 'credential_url': 'https://youtube.com/watch?v=123'})
        self.certificate.refresh_from_db()
        self.assertEqual(self.certificate.verification_status, 'PENDING')
        self.assertIsNone(self.certificate.reviewed_by_id)
        self.assertTrue(AuditLog.objects.filter(action='certificate.approval_reset',
            target_id=str(self.certificate.pk)).exists())

    def test_cleanup_command_defaults_to_dry_run(self):
        output = StringIO()
        call_command('purge_portfolio_certificates', stdout=output)
        self.assertIn('Dry-run', output.getvalue())
        self.assertEqual(PortfolioCertificate.objects.count(), 1)

    def test_cleanup_command_confirm_removes_only_certificates(self):
        output = StringIO()
        call_command('purge_portfolio_certificates', confirm=True, stdout=output)
        self.assertEqual(PortfolioCertificate.objects.count(), 0)
        self.assertTrue(User.objects.filter(pk=self.student.pk).exists())
        self.assertIn('1 sertifika kaydı silindi.', output.getvalue())
        second_output = StringIO()
        call_command('purge_portfolio_certificates', confirm=True, stdout=second_output)
        self.assertIn('0 sertifika kaydı silindi.', second_output.getvalue())
