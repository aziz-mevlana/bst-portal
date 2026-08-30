from io import StringIO
import re

from django.contrib.auth.models import User
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import PortfolioSettingsForm
from .models import PasswordReset, WebsiteModerationHistory
from alumni.models import AlumniRegistrationRequest
from .roles import bootstrap_bst_authority_group
from .validators import (
    validate_github_username,
    validate_linkedin_slug,
    validate_public_website,
)


class ProfileModernizationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            'modern-profile', 'modern@trakya.edu.tr', 'StrongPassword123!'
        )
        self.user.profile.user_type = 'student'
        self.user.profile.class_level = '2'
        self.user.profile.save()

    def test_social_fields_accept_identifiers_and_reject_urls(self):
        validate_github_username('bst-portal')
        validate_linkedin_slug('bst-mezunu-2026')
        for invalid in ('https://github.com/bst', 'bad--name', '-bad', 'bad-'):
            with self.assertRaises(ValidationError):
                validate_github_username(invalid)
        for invalid in ('https://linkedin.com/in/bst', 'linkedin.com/in/bst', 'bad/path'):
            with self.assertRaises(ValidationError):
                validate_linkedin_slug(invalid)

    def test_public_website_rejects_local_private_credentials_and_ports(self):
        validate_public_website('https://portfolio.example.com/about')
        for invalid in (
            'javascript:alert(1)', 'http://localhost/test', 'http://127.0.0.1',
            'https://10.0.0.3', 'https://user:pass@example.com', 'https://example.com:8443',
        ):
            with self.assertRaises(ValidationError):
                validate_public_website(invalid)

    def test_student_class_constraint_and_teacher_class_cleanup(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            type(self.user.profile).objects.filter(pk=self.user.profile.pk).update(class_level=None)
        self.user.profile.user_type = 'teacher'
        self.user.profile.class_level = '4'
        self.user.profile.save()
        self.user.profile.refresh_from_db()
        self.assertIsNone(self.user.profile.class_level)

    def test_changing_approved_website_returns_it_to_pending_and_records_history(self):
        profile = self.user.profile
        profile.website_url = 'https://old.example.com'
        profile.website_status = 'approved'
        profile.save()
        form = PortfolioSettingsForm(data={
            'headline': 'Backend geliştirici', 'bio': 'Tanıtım', 'graduation_year': '2027',
            'class_level': '2', 'github_username': 'modern-profile',
            'linkedin_slug': 'modern-profile', 'website_url': 'https://new.example.com',
        }, instance=profile)
        self.assertTrue(form.is_valid(), form.errors)
        updated = form.save()
        self.assertEqual(updated.website_status, 'pending')
        self.assertEqual(updated.approved_website_url, '')
        history = WebsiteModerationHistory.objects.get(profile=profile)
        self.assertEqual(history.website_url, 'https://new.example.com')
        self.assertEqual(history.status, 'pending')


class AuthorityAndEmailSecurityTests(TestCase):
    def test_staff_student_group_gets_safe_permissions_but_not_session_termination(self):
        bootstrap_bst_authority_group()
        user = User.objects.create_user('bst-authority', password='StrongPassword123!')
        user.profile.user_type = 'staff_student'
        user.profile.class_level = '3'
        user.profile.save()
        user = User.objects.get(pk=user.pk)
        self.assertTrue(user.has_perm('accounts.moderate_accounts'))
        self.assertTrue(user.has_perm('accounts.review_collaborations'))
        self.assertTrue(user.has_perm('news.delete_article'))
        self.assertFalse(user.has_perm('accounts.end_user_sessions'))

    def test_password_reset_code_is_hashed(self):
        user = User.objects.create_user('reset-user', email='reset@example.com')
        reset = PasswordReset(user=user)
        reset.set_code('123456')
        reset.save()
        self.assertEqual(reset.code, '')
        self.assertNotEqual(reset.code_hash, '123456')
        self.assertTrue(reset.matches_code('123456'))
        self.assertFalse(reset.matches_code('654321'))

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        DEFAULT_FROM_EMAIL='noreply@bst.test', EMAIL_USE_TLS=False, EMAIL_USE_SSL=False,
    )
    def test_password_reset_request_does_not_reveal_account_by_redirect(self):
        User.objects.create_user('known', email='known@example.com')
        known = self.client.post(reverse('accounts:forgot_password'), {'email': 'known@example.com'})
        unknown = self.client.post(reverse('accounts:forgot_password'), {'email': 'unknown@example.com'})
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known['Location'], unknown['Location'])
        self.assertEqual(known['Location'], reverse('accounts:reset_password_verify'))

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
        EMAIL_HOST='', EMAIL_HOST_USER='', EMAIL_HOST_PASSWORD='', DEFAULT_FROM_EMAIL='',
        EMAIL_USE_TLS=True, EMAIL_USE_SSL=False,
    )
    def test_send_test_email_reports_missing_credentials_before_connecting(self):
        with self.assertRaises(CommandError):
            call_command('send_test_email', recipient='test@example.com', stdout=StringIO())

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        DEFAULT_FROM_EMAIL='noreply@bst.test', EMAIL_USE_TLS=False, EMAIL_USE_SSL=False,
    )
    def test_send_test_email_command_sends_one_message(self):
        call_command('send_test_email', recipient='test@example.com', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['test@example.com'])


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='noreply@bst.test', EMAIL_USE_TLS=False, EMAIL_USE_SSL=False,
    INSTITUTIONAL_EMAIL_DOMAINS={'trakya.edu.tr'},
)
class AlumniPublicRegistrationTests(TestCase):
    def test_alumni_can_use_personal_email_and_becomes_inactive_pending_request(self):
        email = 'mezun.personal@example.com'
        response = self.client.post(reverse('accounts:register'), {
            'first_name': 'Ece', 'last_name': 'Mezun', 'email': email,
            'student_number': '2018000456', 'graduation_year': '2022',
            'password_1': 'StrongPassword123!', 'password_2': 'StrongPassword123!',
            'user_type': 'alumni', 'accept_terms': 'on',
            'privacy_notice_acknowledged': 'on',
        })
        self.assertRedirects(response, reverse('accounts:verify_email'))
        code = re.search(r'\b\d{6}\b', mail.outbox[-1].body).group(0)
        response = self.client.post(
            reverse('accounts:verify_email'),
            {f'code_{index + 1}': digit for index, digit in enumerate(code)},
        )
        self.assertRedirects(response, reverse('accounts:pending_approval'))
        user = User.objects.get(email=email)
        self.assertFalse(user.is_active)
        self.assertEqual(user.profile.user_type, 'alumni')
        self.assertEqual(user.profile.account_status, 'pending_review')
        registration = AlumniRegistrationRequest.objects.get(user=user)
        self.assertEqual(registration.status, 'pending')
        self.assertEqual(registration.student_number, '2018000456')

    def test_student_registration_requires_explicit_valid_class(self):
        response = self.client.post(reverse('accounts:register'), {
            'first_name': 'Ece', 'last_name': 'Öğrenci', 'email': 'ece@trakya.edu.tr',
            'student_number': '2300000456', 'class_level': '',
            'password_1': 'StrongPassword123!', 'password_2': 'StrongPassword123!',
            'user_type': 'student', 'accept_terms': 'on',
            'privacy_notice_acknowledged': 'on',
        })
        self.assertRedirects(response, reverse('accounts:register'))
        self.assertFalse(User.objects.filter(email='ece@trakya.edu.tr').exists())
