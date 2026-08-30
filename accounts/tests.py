from datetime import timedelta
from unittest.mock import patch
import re

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .email_service import EmailConfigurationError, validate_email_configuration
from .models import CommunityRegistration, ConsentRecord, DataSubjectRequest, EmailVerification
from django.contrib.auth.models import User
from projects.models import Project, ProjectType, Team
from core.models import Notification
from events.models import Event


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='noreply@bstakademi.test',
    EMAIL_USE_TLS=False,
    EMAIL_USE_SSL=False,
)
class EmailVerificationFlowTests(TestCase):
    def test_registration_sends_code_and_opens_verification_step(self):
        response = self.client.post(
            reverse('accounts:register'),
            {
                'first_name': 'Test',
                'last_name': 'Ogrenci',
                'email': 'student@trakya.edu.tr',
                'student_number': '2300000000',
                'class_level': '1',
                'password_1': 'StrongPassword123!',
                'password_2': 'StrongPassword123!',
                'user_type': 'student',
                'accept_terms': 'on',
                'privacy_notice_acknowledged': 'on',
            },
        )

        self.assertRedirects(response, reverse('accounts:verify_email'))
        verification = EmailVerification.objects.get(email='student@trakya.edu.tr')
        self.assertNotIn('password', verification.session_data)
        self.assertTrue(verification.password_hash.startswith('pbkdf2_'))
        self.assertEqual(self.client.session['verify_email'], 'student@trakya.edu.tr')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(verification.code, '')
        sent_code = re.search(r'\b\d{6}\b', mail.outbox[0].body).group(0)
        self.assertTrue(verification.matches_code(sent_code))

    def test_resend_requires_post_and_restarts_expiration_window(self):
        verification = EmailVerification.objects.create(
            email='student@example.com',
            code='111111',
            session_data={
                'first_name': 'Test',
                'last_name': 'Ogrenci',
                'user_type': 'student',
            },
        )
        expired_at = timezone.now() - timedelta(minutes=20)
        EmailVerification.objects.filter(pk=verification.pk).update(
            created_at=expired_at
        )
        session = self.client.session
        session['verify_email'] = verification.email
        session.save()

        get_response = self.client.get(reverse('accounts:resend_verification'))
        self.assertEqual(get_response.status_code, 405)

        with patch.object(EmailVerification, 'generate_code', return_value='222222'):
            response = self.client.post(reverse('accounts:resend_verification'))

        self.assertRedirects(response, reverse('accounts:verify_email'))
        verification.refresh_from_db()
        self.assertEqual(verification.code, '')
        self.assertTrue(verification.matches_code('222222'))
        self.assertGreater(verification.created_at, expired_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('222222', mail.outbox[0].body)

    def test_public_registration_cannot_assign_privileged_role(self):
        response = self.client.post(
            reverse('accounts:register'),
            {
                'first_name': 'Yetkisiz',
                'last_name': 'Kullanici',
                'email': 'attacker@example.com',
                'student_number': '2300000001',
                'password_1': 'StrongPassword123!',
                'password_2': 'StrongPassword123!',
                'user_type': 'staff_student',
                'accept_terms': 'on',
                'privacy_notice_acknowledged': 'on',
            },
        )
        self.assertRedirects(response, reverse('accounts:register'))
        self.assertFalse(EmailVerification.objects.filter(email='attacker@example.com').exists())

    def test_verified_user_uses_prehashed_password(self):
        self.client.post(
            reverse('accounts:register'),
            {
                'first_name': 'Test',
                'last_name': 'Ogrenci',
                'email': 'verified@trakya.edu.tr',
                'student_number': '2300000002',
                'class_level': '2',
                'password_1': 'StrongPassword123!',
                'password_2': 'StrongPassword123!',
                'user_type': 'student',
                'accept_terms': 'on',
                'privacy_notice_acknowledged': 'on',
            },
        )
        verification = EmailVerification.objects.get(email='verified@trakya.edu.tr')
        sent_code = re.search(r'\b\d{6}\b', mail.outbox[-1].body).group(0)
        response = self.client.post(
            reverse('accounts:verify_email'),
            {f'code_{i + 1}': digit for i, digit in enumerate(sent_code)},
        )
        self.assertRedirects(response, reverse('accounts:login'))
        user = User.objects.get(email='verified@trakya.edu.tr')
        self.assertTrue(user.check_password('StrongPassword123!'))
        self.assertEqual(ConsentRecord.objects.filter(user=user).count(), 3)


class EmailConfigurationTests(TestCase):
    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
        EMAIL_HOST='smtp.gmail.com',
        EMAIL_HOST_USER='',
        EMAIL_HOST_PASSWORD='',
        DEFAULT_FROM_EMAIL='',
        EMAIL_USE_TLS=True,
        EMAIL_USE_SSL=False,
    )
    def test_missing_smtp_credentials_are_reported_before_connecting(self):
        with self.assertRaises(EmailConfigurationError):
            validate_email_configuration()


class PortfolioPrivacyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            'portfolio-user',
            'private@example.com',
            'StrongPassword123!',
            first_name='Deniz',
            last_name='Öğrenci',
        )
        self.profile = self.user.profile
        self.profile.user_type = 'student'
        self.profile.phone_number = '05550000000'
        self.profile.bio = 'Public biyografi'
        self.profile.save()

    def test_public_portfolio_hides_email_and_phone_by_default(self):
        response = self.client.get(
            reverse('portal:portfolio_detail', args=[self.profile.public_slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public biyografi')
        self.assertNotContains(response, 'private@example.com')
        self.assertNotContains(response, '05550000000')

    def test_private_portfolio_is_only_visible_to_owner(self):
        self.profile.is_portfolio_public = False
        self.profile.save(update_fields=['is_portfolio_public'])
        url = reverse('portal:portfolio_detail', args=[self.profile.public_slug])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_talent_page_only_lists_public_student_profiles(self):
        response = self.client.get(reverse('portal:talent_list'))
        self.assertContains(response, 'Deniz Öğrenci')
        self.profile.is_portfolio_public = False
        self.profile.save(update_fields=['is_portfolio_public'])
        response = self.client.get(reverse('portal:talent_list'))
        self.assertNotContains(response, 'Deniz Öğrenci')

    def test_portfolio_feedback_is_owner_scoped_and_has_no_hiring_prediction(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('accounts:portfolio_feedback'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Henüz proje yok')
        self.assertContains(response, 'işe alınma veya başarı tahmini değildir')

    def test_portfolio_feedback_requires_login(self):
        response = self.client.get(reverse('accounts:portfolio_feedback'))
        self.assertEqual(response.status_code, 302)


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='noreply@bstakademi.test',
    EMAIL_USE_TLS=False,
    EMAIL_USE_SSL=False,
    INSTITUTIONAL_EMAIL_DOMAINS={'trakya.edu.tr'},
)
class InstitutionalRegistrationTests(TestCase):
    def setUp(self):
        cache.clear()

    def registration_data(self, **overrides):
        data = {
            'first_name': 'Ece', 'last_name': 'Öğrenci',
            'email': 'ece@trakya.edu.tr', 'student_number': '2300000099',
            'class_level': '3',
            'password_1': 'StrongPassword123!', 'password_2': 'StrongPassword123!',
            'user_type': 'student', 'accept_terms': 'on', 'privacy_notice_acknowledged': 'on',
        }
        data.update(overrides)
        return data

    def test_exact_domain_is_required_and_similar_domain_is_rejected(self):
        self.client.post(reverse('accounts:register'), self.registration_data(email='ece@sahte-trakya.edu.tr'))
        self.assertFalse(EmailVerification.objects.exists())
        self.client.post(reverse('accounts:register'), self.registration_data())
        self.assertTrue(EmailVerification.objects.filter(email='ece@trakya.edu.tr').exists())

    def test_teacher_is_not_approved_by_email_verification_alone(self):
        self.client.post(reverse('accounts:register'), self.registration_data(
            email='hoca@trakya.edu.tr', student_number='', user_type='teacher', teacher_title='dr',
        ))
        code = re.search(r'\b\d{6}\b', mail.outbox[-1].body).group(0)
        self.client.post(reverse('accounts:verify_email'), {f'code_{i + 1}': digit for i, digit in enumerate(code)})
        user = User.objects.get(email='hoca@trakya.edu.tr')
        self.assertFalse(user.is_active)
        self.assertEqual(user.profile.account_status, 'pending_review')
        self.assertIsNotNone(user.profile.institutional_email_verified_at)

    def test_duplicate_student_number_is_rejected(self):
        existing = User.objects.create_user('existing-student', 'existing@trakya.edu.tr', 'StrongPassword123!')
        existing.profile.student_number = '2300000099'
        existing.profile.save(update_fields=['student_number'])
        self.client.post(reverse('accounts:register'), self.registration_data(email='new@trakya.edu.tr'))
        self.assertFalse(EmailVerification.objects.filter(email='new@trakya.edu.tr').exists())


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='noreply@bstakademi.test',
    EMAIL_USE_TLS=False,
    EMAIL_USE_SSL=False,
    INSTITUTIONAL_EMAIL_DOMAINS={'trakya.edu.tr'},
)
class AccountSettingsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('settings-user', 'old@trakya.edu.tr', 'StrongPassword123!', first_name='Eski')
        self.user.profile.user_type = 'student'
        self.user.profile.save(update_fields=['user_type'])
        self.client.force_login(self.user)

    def test_user_can_update_own_account_but_not_role(self):
        response = self.client.post(reverse('accounts:account_settings_update'), {
            'first_name': 'Yeni', 'last_name': 'Ad', 'username': 'settings-user',
            'phone_number': '05550000000', 'user_type': 'staff_student',
        })
        self.assertRedirects(response, reverse('accounts:portfolio_settings'))
        self.user.refresh_from_db()
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Yeni')
        self.assertEqual(self.user.profile.phone_number, '05550000000')
        self.assertEqual(self.user.profile.user_type, 'student')

    def test_email_does_not_change_before_new_address_is_verified(self):
        response = self.client.post(reverse('accounts:email_change_request'), {'new_email': 'new@trakya.edu.tr'})
        self.assertRedirects(response, reverse('accounts:email_change_verify'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'old@trakya.edu.tr')
        code = re.search(r'\b\d{6}\b', mail.outbox[-1].body).group(0)
        self.client.post(reverse('accounts:email_change_verify'), {'code': code})
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new@trakya.edu.tr')

    def test_password_change_preserves_current_session(self):
        response = self.client.post(reverse('accounts:password_change'), {
            'old_password': 'StrongPassword123!',
            'new_password1': 'NewStrongPassword456!',
            'new_password2': 'NewStrongPassword456!',
        })
        self.assertRedirects(response, reverse('accounts:portfolio_settings'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewStrongPassword456!'))
        self.assertEqual(self.client.get(reverse('accounts:portfolio_settings')).status_code, 200)

    def test_student_can_delete_account_with_owned_project_and_team(self):
        team = Team.objects.create(name='Silinecek ekip', leader=self.user)
        project = Project.objects.create(
            project_type=ProjectType.objects.get(code='INDEPENDENT'),
            title='Silinecek proje',
            created_by=self.user,
            team_entity=team,
        )
        user_pk = self.user.pk
        team_pk = team.pk
        project_pk = project.pk

        response = self.client.post(
            reverse('accounts:account_delete'),
            {'current_password': 'StrongPassword123!', 'confirmation_text': 'DELETE'},
        )

        self.assertRedirects(response, reverse('portal:index'))
        self.assertFalse(User.objects.filter(pk=user_pk).exists())
        self.assertFalse(Team.objects.filter(pk=team_pk).exists())
        self.assertFalse(Project.objects.filter(pk=project_pk).exists())

    def test_temporary_password_forces_change_and_unlocks_account_after_update(self):
        self.user.profile.must_change_password = True
        self.user.profile.save(update_fields=['must_change_password'])

        blocked = self.client.get(reverse('portal:index'))
        self.assertRedirects(
            blocked,
            reverse('accounts:portfolio_settings'),
            fetch_redirect_response=False,
        )
        settings_page = self.client.get(reverse('accounts:portfolio_settings'))
        self.assertContains(settings_page, 'Geçici şifrenizi değiştirin')
        self.assertContains(settings_page, 'Güvenlik bölümüne git')
        self.assertNotContains(settings_page, "window.scrollTo(0, 0)")

        response = self.client.post(reverse('accounts:password_change'), {
            'old_password': 'StrongPassword123!',
            'new_password1': 'PermanentPassword789!',
            'new_password2': 'PermanentPassword789!',
        })

        self.assertRedirects(response, reverse('accounts:portfolio_settings'))
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.must_change_password)
        self.assertEqual(self.client.get(reverse('portal:index')).status_code, 200)

    def test_settings_page_uses_polished_navigation_turkish_labels_and_enhanced_multiselects(self):
        response = self.client.get(reverse('accounts:portfolio_settings'))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            'autofocus',
            response.context['password_form'].fields['old_password'].widget.attrs,
        )
        self.assertContains(response, "window.location.hash === '#security'")
        self.assertNotContains(response, 'window.scrollTo')
        self.assertContains(response, 'css/account-settings.css?v=20260821.2')
        self.assertContains(response, 'aria-label="Ayar bölümleri"')
        self.assertContains(response, 'Portfolyom herkese açık')
        self.assertContains(response, 'Sertifika adı')
        self.assertContains(response, 'Talep türü')
        self.assertContains(response, 'data-enhance-multiselect="true"', count=2)
        self.assertNotContains(response, 'Is portfolio public')
        self.assertNotContains(response, '>Title<')

    def test_private_social_links_and_contact_are_not_public(self):
        profile = self.user.profile
        profile.github_username = 'private-user'
        profile.linkedin_slug = 'private-user'
        profile.phone_number = '05551112233'
        profile.show_github = False
        profile.show_linkedin = False
        profile.show_email = False
        profile.show_phone = False
        profile.save()
        self.client.logout()
        response = self.client.get(reverse('portal:portfolio_detail', args=[profile.public_slug]))
        self.assertNotContains(response, 'github.com/private-user')
        self.assertNotContains(response, 'linkedin.com/in/private-user')
        self.assertNotContains(response, 'old@trakya.edu.tr')
        self.assertNotContains(response, '05551112233')


class ProfileShowcaseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('showcase-user', 'showcase@trakya.edu.tr', 'StrongPassword123!')
        self.other = User.objects.create_user('showcase-other', 'other@trakya.edu.tr', 'StrongPassword123!')
        project_type = ProjectType.objects.get(code='INDEPENDENT')
        self.project = Project.objects.create(
            project_type=project_type,
            title='Sergilenecek proje',
            description='Kullanıcının seçtiği proje',
            created_by=self.user,
            visibility='public',
            approval_status='approved',
            development_status='completed',
        )
        self.unselected = Project.objects.create(
            project_type=project_type,
            title='Seçilmemiş proje',
            created_by=self.user,
            visibility='public',
            approval_status='approved',
            development_status='completed',
        )
        self.foreign_project = Project.objects.create(
            project_type=project_type,
            title='Başkasının projesi',
            created_by=self.other,
            visibility='public',
            approval_status='approved',
            development_status='completed',
        )
        self.client.force_login(self.user)

    def test_profile_page_is_project_showcase_not_legacy_settings(self):
        response = self.client.get(reverse('accounts:profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Proje sergisi')
        self.assertContains(response, 'Profilimde hangi projeler görünsün?')
        self.assertNotContains(response, 'Profil Ayarları')

    def test_user_can_select_only_own_eligible_projects(self):
        response = self.client.post(reverse('accounts:profile'), {
            'showcase_projects': [self.project.pk, self.foreign_project.pk],
        })

        self.assertRedirects(response, reverse('accounts:profile'))
        selected = set(self.user.profile.showcase_projects.values_list('pk', flat=True))
        self.assertEqual(selected, {self.project.pk})

    def test_public_portfolio_lists_only_selected_public_projects(self):
        self.user.profile.showcase_projects.add(self.project)
        self.client.logout()

        response = self.client.get(reverse('portal:portfolio_detail', args=[self.user.profile.public_slug]))

        self.assertContains(response, self.project.title)
        self.assertNotContains(response, self.unselected.title)

    def test_other_user_cannot_see_selected_private_project(self):
        self.project.visibility = 'private'
        self.project.save(update_fields=['visibility'])
        self.user.profile.showcase_projects.add(self.project)
        self.client.force_login(self.other)

        response = self.client.get(reverse('accounts:user_profile', args=[self.user.pk]))

        self.assertNotContains(response, self.project.title)

    def test_kvkk_page_contains_required_information_sections(self):
        self.client.logout()
        response = self.client.get(reverse('portal:kvkk_notice'))

        self.assertContains(response, 'Veri sorumlusu ve iletişim')
        self.assertContains(response, 'İşlenen kişisel veri kategorileri')
        self.assertContains(response, 'KVKK kapsamındaki haklarınız')
        self.assertContains(response, 'Başvuru yöntemi')


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='noreply@bstakademi.test',
    EMAIL_USE_TLS=False,
    EMAIL_USE_SSL=False,
)
class CommunityRegistrationFlowTests(TestCase):
    def setUp(self):
        cache.clear()

    def registration_data(self, **overrides):
        data = {
            'first_name': 'Ayşe',
            'last_name': 'Topluluk',
            'email': 'ayse@example.com',
            'password_1': 'StrongPassword123!',
            'password_2': 'StrongPassword123!',
            'user_type': 'other',
            'accept_terms': 'on',
            'privacy_notice_acknowledged': 'on',
        }
        data.update(overrides)
        return data

    def register_and_verify(self, **overrides):
        response = self.client.post(reverse('accounts:register'), self.registration_data(**overrides))
        self.assertRedirects(response, reverse('accounts:verify_email'))
        code = re.search(r'\b\d{6}\b', mail.outbox[-1].body).group(0)
        return self.client.post(
            reverse('accounts:verify_email'),
            {f'code_{index + 1}': digit for index, digit in enumerate(code)},
        )

    def test_other_registration_explains_visitor_first_flow(self):
        response = self.client.get(reverse('accounts:register'))

        self.assertContains(response, 'Diğer')
        self.assertContains(response, '“Diğer” hesapları Ziyaretçi olarak açılır.')
        self.assertNotContains(response, 'name="content_plan"')

    def test_other_registration_creates_active_visitor_without_application(self):
        response = self.register_and_verify()

        self.assertRedirects(response, reverse('accounts:login'))
        user = User.objects.get(email='ayse@example.com')
        self.assertTrue(user.is_active)
        self.assertEqual(user.profile.user_type, 'visitor')
        self.assertIsNone(user.profile.class_level)
        self.assertFalse(CommunityRegistration.objects.filter(user=user).exists())

    def test_visitor_settings_show_approved_member_application_fields(self):
        self.register_and_verify()
        user = User.objects.get(email='ayse@example.com')
        self.client.force_login(user)

        response = self.client.get(reverse('accounts:portfolio_settings'))

        self.assertContains(response, 'Onaylı Üye Başvurusu')
        self.assertContains(response, 'Kendinizi kısaca tanıtın')
        self.assertContains(response, 'Neden Onaylı Üye olmak istiyorsunuz?')
        self.assertContains(response, 'Ne tür paylaşımlar yapmayı düşünüyorsunuz?')
        self.assertContains(response, 'Varsa GitHub/LinkedIn/portfolyo bağlantısı')
        self.assertContains(response, 'Ek açıklama')

    def test_settings_link_to_confirmation_page_not_deletion_request(self):
        self.register_and_verify()
        user = User.objects.get(email='ayse@example.com')
        self.client.force_login(user)

        response = self.client.get(reverse('accounts:portfolio_settings'))

        self.assertContains(response, 'Hesabımı sil')
        self.assertNotContains(response, '<option value="delete">')

        confirmation = self.client.get(reverse('accounts:account_delete'))
        self.assertContains(confirmation, 'Hesabını kalıcı olarak sil')
        self.assertContains(confirmation, 'büyük harflerle')

    def test_visitor_can_delete_account_with_current_password(self):
        self.register_and_verify()
        user = User.objects.get(email='ayse@example.com')
        user_pk = user.pk
        DataSubjectRequest.objects.create(user=user, request_type='delete')
        self.client.force_login(user)

        response = self.client.post(
            reverse('accounts:account_delete'),
            {'current_password': 'StrongPassword123!', 'confirmation_text': 'DELETE'},
        )

        self.assertRedirects(response, reverse('portal:index'))
        self.assertFalse(User.objects.filter(pk=user_pk).exists())
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_visitor_account_deletion_rejects_wrong_password(self):
        self.register_and_verify()
        user = User.objects.get(email='ayse@example.com')
        self.client.force_login(user)

        response = self.client.post(
            reverse('accounts:account_delete'),
            {'current_password': 'WrongPassword!', 'confirmation_text': 'DELETE'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'Mevcut parola hatalı.', status_code=400)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_approved_member_can_also_delete_account(self):
        self.register_and_verify()
        user = User.objects.get(email='ayse@example.com')
        user_pk = user.pk
        user.profile.user_type = 'approved_member'
        user.profile.save(update_fields=['user_type'])
        self.client.force_login(user)

        response = self.client.post(
            reverse('accounts:account_delete'),
            {'current_password': 'StrongPassword123!', 'confirmation_text': 'DELETE'},
        )

        self.assertRedirects(response, reverse('portal:index'))
        self.assertFalse(User.objects.filter(pk=user_pk).exists())

    def test_account_deletion_requires_exact_delete_text(self):
        self.register_and_verify()
        user = User.objects.get(email='ayse@example.com')
        self.client.force_login(user)

        response = self.client.post(
            reverse('accounts:account_delete'),
            {'current_password': 'StrongPassword123!', 'confirmation_text': 'delete'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'tam olarak DELETE yazın', status_code=400)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_admin_account_cannot_use_self_service_deletion(self):
        admin = User.objects.create_superuser('site-admin', 'admin@example.com', 'StrongPassword123!')
        self.client.force_login(admin)

        response = self.client.get(reverse('accounts:account_delete'))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(User.objects.filter(pk=admin.pk).exists())

    def test_visitor_can_submit_approved_member_application(self):
        self.register_and_verify()
        user = User.objects.get(email='ayse@example.com')
        authority = User.objects.create_user('application-authority', 'authority2@trakya.edu.tr', 'StrongPassword123!')
        authority.profile.user_type = 'staff_student'
        authority.profile.save(update_fields=['user_type'])
        self.client.force_login(user)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse('accounts:approved_member_application_submit'),
                {
                    'introduction': 'Yazılım topluluklarını takip ediyorum.',
                    'motivation': 'BST projelerine düzenli katkı sağlamak istiyorum.',
                    'content_plan': 'Teknik rehberler ve açık kaynak proje yazıları.',
                    'reference_url': 'https://github.com/example',
                    'additional_notes': 'Aylık en az bir içerik hazırlayabilirim.',
                },
            )

        self.assertRedirects(
            response,
            f"{reverse('accounts:portfolio_settings')}#approved-member",
            fetch_redirect_response=False,
        )
        application = CommunityRegistration.objects.get(user=user)
        self.assertEqual(application.status, 'pending')
        self.assertTrue(application.wants_to_share)
        self.assertEqual(application.reference_url, 'https://github.com/example')
        self.assertEqual(application.additional_notes, 'Aylık en az bir içerik hazırlayabilirim.')
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.user_type, 'visitor')
        self.assertTrue(Notification.objects.filter(recipient=authority, notification_type='pending_task').exists())

    def test_application_requires_content_plan_and_valid_reference_url(self):
        self.register_and_verify()
        user = User.objects.get(email='ayse@example.com')
        self.client.force_login(user)

        response = self.client.post(
            reverse('accounts:approved_member_application_submit'),
            {
                'introduction': 'Kısa tanıtım',
                'motivation': 'Katkı sunmak istiyorum.',
                'content_plan': '',
                'reference_url': 'github nokta com',
            },
            follow=True,
        )

        self.assertFalse(CommunityRegistration.objects.filter(user=user).exists())
        self.assertContains(response, 'Bu alan zorunludur.')
        self.assertContains(response, 'Geçerli bir URL girin.')

    def test_rejected_visitor_can_update_and_resubmit_application(self):
        user = User.objects.create_user('reapply-visitor', 'reapply@example.com', 'StrongPassword123!')
        user.profile.user_type = 'visitor'
        user.profile.save(update_fields=['user_type'])
        application = CommunityRegistration.objects.create(
            user=user,
            introduction='Eski tanıtım',
            motivation='Eski neden',
            wants_to_share=True,
            content_plan='Eski plan',
            status='rejected',
            reviewer_note='Daha ayrıntılı bilgi gerekli.',
        )
        self.client.force_login(user)

        self.client.post(
            reverse('accounts:approved_member_application_submit'),
            {
                'introduction': 'Güncellenmiş ve ayrıntılı tanıtım.',
                'motivation': 'Uzun vadeli katkı sunmak istiyorum.',
                'content_plan': 'Açık kaynak proje günlükleri ve teknik rehberler.',
                'reference_url': 'https://www.linkedin.com/in/example',
                'additional_notes': '',
            },
        )

        application.refresh_from_db()
        self.assertEqual(application.status, 'pending')
        self.assertEqual(application.reviewer_note, '')
        self.assertIsNone(application.reviewed_by)
        self.assertEqual(application.introduction, 'Güncellenmiş ve ayrıntılı tanıtım.')


class ApprovedMemberApplicationReviewTests(TestCase):
    def setUp(self):
        self.applicant = User.objects.create_user(
            'community-applicant', 'applicant@example.com', 'StrongPassword123!'
        )
        self.applicant.profile.user_type = 'visitor'
        self.applicant.profile.save(update_fields=['user_type'])
        self.application = CommunityRegistration.objects.create(
            user=self.applicant,
            introduction='Ürün geliştirme topluluklarında yer alıyorum.',
            motivation='BST projelerine içerikle katkı sağlamak istiyorum.',
            wants_to_share=True,
            content_plan='Proje vaka çalışmaları ve teknik yazılar.',
            reference_url='https://github.com/community-applicant',
            additional_notes='Düzenli paylaşım yapabilirim.',
            status='pending',
        )
        self.authority = User.objects.create_user(
            'community-authority', 'authority@trakya.edu.tr', 'StrongPassword123!'
        )
        self.authority.profile.user_type = 'staff_student'
        self.authority.profile.save(update_fields=['user_type'])

    def test_bst_authority_can_review_and_approve_member(self):
        self.assertTrue(self.authority.has_perm('accounts.review_contributor_applications'))
        self.client.force_login(self.authority)

        listing = self.client.get(reverse('dashboard:approved_member_applications'))
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, 'Proje vaka çalışmaları ve teknik yazılar.')
        self.assertContains(listing, 'https://github.com/community-applicant')
        response = self.client.post(
            reverse('dashboard:approved_member_application_review', args=[self.application.pk]),
            {'action': 'approve', 'reviewer_note': 'İçerik planı uygun.'},
        )

        self.assertRedirects(response, reverse('dashboard:approved_member_applications'))
        self.application.refresh_from_db()
        self.applicant.profile.refresh_from_db()
        self.assertEqual(self.application.status, 'approved')
        self.assertEqual(self.application.reviewed_by, self.authority)
        self.assertEqual(self.applicant.profile.user_type, 'approved_member')
        self.assertTrue(Notification.objects.filter(recipient=self.applicant, notification_type='moderation').exists())

    def test_rejection_requires_note_and_keeps_visitor_role(self):
        self.client.force_login(self.authority)
        url = reverse('dashboard:approved_member_application_review', args=[self.application.pk])

        self.client.post(url, {'action': 'reject', 'reviewer_note': ''})
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'pending')

        self.client.post(url, {'action': 'reject', 'reviewer_note': 'Başvuru daha somut olmalı.'})
        self.application.refresh_from_db()
        self.applicant.profile.refresh_from_db()
        self.assertEqual(self.application.status, 'rejected')
        self.assertEqual(self.applicant.profile.user_type, 'visitor')

    def test_unprivileged_user_cannot_review(self):
        self.client.force_login(self.applicant)
        self.assertEqual(self.client.get(reverse('dashboard:approved_member_applications')).status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse('dashboard:approved_member_application_review', args=[self.application.pk]),
                {'action': 'approve'},
            ).status_code,
            403,
        )


class CommunityRolePermissionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('project-owner', 'owner@example.com', 'StrongPassword123!')
        self.visitor = User.objects.create_user('portal-visitor', 'visitor@example.com', 'StrongPassword123!')
        self.visitor.profile.user_type = 'visitor'
        self.visitor.profile.save(update_fields=['user_type'])
        project_type = ProjectType.objects.get(code='INDEPENDENT')
        self.project = Project.objects.create(
            project_type=project_type,
            title='Herkese Açık Proje',
            description='Ziyaretçi etkileşimi için proje.',
            created_by=self.owner,
            visibility='public',
            approval_status='approved',
        )
        self.client.force_login(self.visitor)

    def test_visitor_can_comment_like_and_save_public_project(self):
        comment_response = self.client.post(
            reverse('projects:add_comment', args=[self.project.pk]),
            {'content': 'Faydalı bir proje olmuş.'},
        )
        like_response = self.client.post(reverse('projects:toggle_project_like', args=[self.project.pk]))
        save_response = self.client.post(reverse('projects:toggle_project_save', args=[self.project.pk]))

        self.assertEqual(comment_response.status_code, 302)
        self.assertEqual(like_response.status_code, 302)
        self.assertEqual(save_response.status_code, 302)
        self.assertTrue(self.project.comments.filter(author=self.visitor).exists())
        self.assertTrue(self.project.likes.filter(user=self.visitor).exists())
        self.assertTrue(self.project.saves.filter(user=self.visitor).exists())

    def test_visitor_cannot_create_project_or_team(self):
        self.assertEqual(self.client.get(reverse('projects:project_create')).status_code, 403)
        self.assertEqual(self.client.get(reverse('projects:team_create')).status_code, 403)

    def test_visitor_cannot_register_for_event(self):
        event = Event.objects.create(
            title='Topluluk Etkinliği',
            description='Test etkinliği',
            event_type='workshop',
            location='Çevrim içi',
            start_date=timezone.now() + timedelta(days=7),
            end_date=timezone.now() + timedelta(days=7, hours=2),
            created_by=self.owner,
            allow_registration=True,
        )

        self.assertEqual(
            self.client.post(reverse('events:event_register', args=[event.pk])).status_code,
            403,
        )

    def test_approved_member_can_open_content_creation(self):
        self.visitor.profile.user_type = 'approved_member'
        self.visitor.profile.save(update_fields=['user_type'])

        self.assertEqual(self.client.get(reverse('projects:project_create')).status_code, 200)
        self.assertEqual(self.client.get(reverse('news:create_news')).status_code, 200)
