from django.core.cache import cache
from django.db import IntegrityError
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
import json
from unittest.mock import patch
from accounts.models import UserModerationAction
from accounts.roles import bootstrap_bst_authority_group
from core.models import AuditLog, Notification


class PublicPageSmokeTests(TestCase):
    def test_home_page_loads(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)

    def test_public_shell_loads_cache_safe_ui_layer(self):
        response = self.client.get('/')

        self.assertContains(response, 'css/bst-ui-v2.css?v=20260830.2')
        self.assertContains(response, 'css/mobile-ui.css?v=20260830.1')


class AcademicApprovalPermissionTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('teacher', 'teacher@example.com', 'StrongPassword123!')
        self.teacher.profile.user_type = 'teacher'
        self.teacher.profile.save()
        self.pending = User.objects.create_user(
            'pending', 'pending@example.com', 'StrongPassword123!', is_active=False
        )
        self.pending.profile.user_type = 'teacher'
        self.pending.profile.save()

    def test_teacher_cannot_approve_academic(self):
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('dashboard:approve_academic'),
            data='{"user_id": %s}' % self.pending.id,
            content_type='application/json',
        )
        self.assertFalse(response.json()['success'])
        self.pending.refresh_from_db()
        self.assertFalse(self.pending.is_active)

    def test_staff_can_approve_academic(self):
        staff = User.objects.create_user(
            'admin', 'admin@example.com', 'StrongPassword123!', is_staff=True
        )
        self.client.force_login(staff)
        response = self.client.post(
            reverse('dashboard:approve_academic'),
            data='{"user_id": %s}' % self.pending.id,
            content_type='application/json',
        )
        self.assertTrue(response.json()['success'])
        self.pending.refresh_from_db()
        self.assertTrue(self.pending.is_active)


class NavigationPermissionTests(TestCase):
    def make_user(self, username, role, **kwargs):
        user = User.objects.create_user(
            username,
            f'{username}@example.com',
            'StrongPassword123!',
            **kwargs,
        )
        user.profile.user_type = role
        user.profile.save(update_fields=['user_type'])
        return user

    def test_student_sees_personal_panel_but_not_management_panel(self):
        student = self.make_user('nav-student', 'student')
        self.client.force_login(student)
        response = self.client.get(reverse('portal:index'))
        self.assertContains(response, 'Öğrenci Paneli')
        self.assertNotContains(response, 'Yönetim Paneli')

    def test_alumni_does_not_see_management_panel(self):
        alumni = self.make_user('nav-alumni', 'alumni')
        self.client.force_login(alumni)
        response = self.client.get(reverse('portal:index'))
        self.assertNotContains(response, 'Yönetim Paneli')

    def test_visitor_has_no_panel_link_and_dashboard_redirects_home(self):
        visitor = self.make_user('nav-visitor', 'visitor')
        self.client.force_login(visitor)

        response = self.client.get(reverse('portal:index'))
        self.assertNotContains(response, 'Ziyaretçi Paneli')
        self.assertNotContains(response, f'href="{reverse("dashboard:home")}"')
        self.assertRedirects(
            self.client.get(reverse('dashboard:home')),
            reverse('portal:index'),
        )

    def test_teacher_and_authorized_student_receive_distinct_panels(self):
        teacher = self.make_user('nav-teacher', 'teacher')
        self.client.force_login(teacher)
        self.assertContains(self.client.get(reverse('portal:index')), 'Yönetim Paneli')
        self.client.logout()

        authority = self.make_user('nav-staff-student', 'staff_student')
        self.client.force_login(authority)
        response = self.client.get(reverse('portal:index'))
        self.assertContains(response, 'BST Yetkilisi Paneli')
        self.assertNotContains(response, '>Yönetim Paneli<')
        dashboard = self.client.get(reverse('dashboard:home'))
        self.assertContains(dashboard, 'Öğrenci çalışma alanı')
        self.assertContains(dashboard, 'Öğrenci profilin korunuyor')

    def test_django_staff_sees_management_panel_even_with_student_profile(self):
        staff = self.make_user('nav-staff', 'student', is_staff=True)
        self.client.force_login(staff)
        response = self.client.get(reverse('portal:index'))
        self.assertContains(response, 'Yönetim Paneli')

    def test_superuser_with_legacy_authority_role_remains_admin_only(self):
        admin = self.make_user(
            'nav-legacy-admin', 'staff_student', is_staff=True, is_superuser=True
        )
        self.client.force_login(admin)

        response = self.client.get(reverse('dashboard:home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Yönetim Paneli')
        self.assertNotContains(response, 'Öğrenci Alanım')
        self.assertNotContains(response, 'Öğrenci çalışma alanı')
        self.assertFalse(admin.groups.filter(name='BST Yetkilisi').exists())

    def test_normal_student_cannot_open_management_user_list_directly(self):
        student = self.make_user('direct-student', 'student')
        self.client.force_login(student)
        self.assertEqual(self.client.get(reverse('dashboard:students')).status_code, 403)
        self.assertEqual(self.client.get(reverse('dashboard:students_load_more')).status_code, 403)

    def test_teacher_can_open_management_student_list(self):
        teacher = self.make_user('direct-teacher', 'teacher')
        self.client.force_login(teacher)
        self.assertEqual(self.client.get(reverse('dashboard:students')).status_code, 200)

    def test_event_management_uses_dashboard_shell(self):
        teacher = self.make_user('event-manager', 'teacher')
        self.client.force_login(teacher)
        response = self.client.get(reverse('dashboard:events'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dashboard-shell')
        self.assertContains(response, 'Etkinlik listesi')

    def test_academic_approval_page_remains_real_admin_only(self):
        teacher = self.make_user('limited-teacher', 'teacher')
        self.client.force_login(teacher)
        self.assertEqual(self.client.get(reverse('dashboard:academics')).status_code, 403)

    def test_dashboard_logout_uses_post_form(self):
        teacher = self.make_user('logout-teacher', 'teacher')
        self.client.force_login(teacher)

        response = self.client.get(reverse('dashboard:home'))

        logout_url = reverse('accounts:logout')
        self.assertContains(response, f'method="post" action="{logout_url}"')
        self.assertNotContains(response, f'href="{logout_url}"')
        self.assertEqual(self.client.get(logout_url).status_code, 405)


class DashboardUserSearchSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse('dashboard:search_users')
        self.target = User.objects.create_user(
            'search-target',
            'search-target@example.com',
            'StrongPassword123!',
            first_name='Aranan',
            last_name='Kullanıcı',
        )
        self.student = self.make_user('search-student', 'student')
        self.teacher = self.make_user('search-teacher', 'teacher')
        self.authority = self.make_user('search-authority', 'staff_student')
        bootstrap_bst_authority_group()
        self.staff = self.make_user('search-staff', 'student', is_staff=True)
        self.superuser = self.make_user('search-superuser', 'student', is_superuser=True)

    def make_user(self, username, role, **kwargs):
        user = User.objects.create_user(
            username,
            f'{username}@example.com',
            'StrongPassword123!',
            **kwargs,
        )
        user.profile.user_type = role
        user.profile.save(update_fields=['user_type'])
        return user

    def test_anonymous_request_gets_json_forbidden_without_user_data(self):
        response = self.client.get(self.url, {'q': 'search-target'})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {'error': 'Yetkiniz yok.'})
        self.assertNotContains(response, self.target.email, status_code=403)

    def test_non_admin_roles_get_json_forbidden_without_user_data(self):
        for user in (self.student, self.teacher, self.authority):
            with self.subTest(role=user.profile.user_type):
                self.client.force_login(user)
                response = self.client.get(self.url, {'q': 'search-target'})
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {'error': 'Yetkiniz yok.'})
                self.assertNotContains(response, self.target.email, status_code=403)

    def test_django_staff_can_search(self):
        self.client.force_login(self.staff)

        response = self.client.get(self.url, {'q': 'Aranan'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'][0]['id'], self.target.pk)

    def test_superuser_can_search_even_without_staff_flag(self):
        self.assertFalse(self.superuser.is_staff)
        self.client.force_login(self.superuser)

        response = self.client.get(self.url, {'q': 'Aranan'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'][0]['id'], self.target.pk)

    def test_post_is_rejected(self):
        self.client.force_login(self.staff)

        response = self.client.post(self.url, {'q': 'Aranan'})

        self.assertEqual(response.status_code, 405)

    def test_short_or_whitespace_query_returns_no_results(self):
        self.client.force_login(self.staff)
        for query in ('', 'a', '  a  ', '   '):
            with self.subTest(query=query):
                response = self.client.get(self.url, {'q': query})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {'results': []})

    def test_admin_search_is_bounded_and_returns_only_frontend_contract(self):
        for index in range(25):
            User.objects.create_user(
                f'bounded-{index}',
                f'bounded-{index}@example.com',
                'StrongPassword123!',
                first_name='BoundedSearch',
            )
        self.client.force_login(self.staff)

        response = self.client.get(self.url, {'q': 'BoundedSearch'})

        self.assertEqual(response.status_code, 200)
        results = response.json()['results']
        self.assertEqual(len(results), 20)
        self.assertEqual(
            set(results[0]),
            {'id', 'name', 'email', 'user_type', 'already_matched'},
        )

    def test_rate_limit_returns_429_json(self):
        self.client.force_login(self.staff)

        for _ in range(30):
            self.assertEqual(self.client.get(self.url, {'q': 'Aranan'}).status_code, 200)
        response = self.client.get(self.url, {'q': 'Aranan'})

        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            response.json(),
            {'error': 'Çok fazla arama isteği gönderildi. Lütfen kısa süre sonra tekrar deneyin.'},
        )

    def test_alumni_search_frontend_handles_json_errors_safely(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse('dashboard:alumni'))

        self.assertContains(response, 'if (!response.ok)')
        self.assertContains(response, "textContent = error.message")


class StudentClassLevelAdminTests(TestCase):
    def setUp(self):
        self.url = reverse('dashboard:update_student_class')
        self.student = self.make_user('class-target', 'student')
        self.staff_student = self.make_user('class-authority', 'staff_student')
        self.teacher = self.make_user('class-teacher', 'teacher')
        self.staff = self.make_user('class-staff', 'student', is_staff=True)
        self.superuser = self.make_user('class-superuser', 'student', is_superuser=True)

    def make_user(self, username, role, **kwargs):
        user = User.objects.create_user(
            username,
            f'{username}@example.com',
            'StrongPassword123!',
            **kwargs,
        )
        user.profile.user_type = role
        user.profile.save(update_fields=['user_type'])
        return user

    def post_update(self, actor, target=None, class_level='4', **payload_overrides):
        self.client.force_login(actor)
        payload = {
            'student_id': (target or self.student).pk,
            'class_level': class_level,
        }
        payload.update(payload_overrides)
        return self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_student_teacher_and_staff_student_are_forbidden(self):
        for actor in (self.student, self.teacher, self.staff_student):
            with self.subTest(role=actor.profile.user_type):
                response = self.post_update(actor)
                self.assertEqual(response.status_code, 403)
                self.assertFalse(response.json()['success'])
        self.student.profile.refresh_from_db()
        self.assertEqual(self.student.profile.class_level, '1')
        self.assertFalse(AuditLog.objects.filter(action='student.class_level_changed').exists())

    def test_only_post_is_accepted(self):
        self.client.force_login(self.staff)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)

    def test_django_staff_can_change_student_class_and_creates_audit_log(self):
        response = self.post_update(self.staff, class_level='3')

        self.assertEqual(response.status_code, 200)
        self.student.profile.refresh_from_db()
        self.assertEqual(self.student.profile.class_level, '3')
        audit = AuditLog.objects.get(action='student.class_level_changed')
        self.assertEqual(audit.actor, self.staff)
        self.assertEqual(audit.target_type, 'auth.user')
        self.assertEqual(audit.target_id, str(self.student.pk))
        self.assertEqual(audit.metadata, {
            'old_class_level': '1',
            'new_class_level': '3',
        })

    def test_superuser_can_change_staff_student_class(self):
        response = self.post_update(
            self.superuser,
            target=self.staff_student,
            class_level='2',
        )

        self.assertEqual(response.status_code, 200)
        self.staff_student.profile.refresh_from_db()
        self.assertEqual(self.staff_student.profile.class_level, '2')

    def test_non_student_targets_are_rejected_without_audit(self):
        targets = [
            self.teacher,
            self.make_user('class-alumni', 'alumni'),
            self.make_user('class-visitor', 'visitor'),
        ]

        for target in targets:
            with self.subTest(role=target.profile.user_type):
                response = self.post_update(self.staff, target=target, class_level='2')
                self.assertEqual(response.status_code, 400)
        self.assertFalse(AuditLog.objects.filter(action='student.class_level_changed').exists())

    def test_invalid_class_levels_are_rejected_without_mutation_or_audit(self):
        for value in (0, 5, '', None, 'keyfi'):
            with self.subTest(class_level=value):
                response = self.post_update(self.staff, class_level=value)
                self.assertEqual(response.status_code, 400)

        self.student.profile.refresh_from_db()
        self.assertEqual(self.student.profile.class_level, '1')
        self.assertFalse(AuditLog.objects.filter(action='student.class_level_changed').exists())

    def test_missing_or_invalid_student_id_returns_400(self):
        for student_id in (None, '', 0, 999999):
            with self.subTest(student_id=student_id):
                response = self.post_update(
                    self.staff,
                    student_id=student_id,
                )
                self.assertEqual(response.status_code, 400)
        self.assertFalse(AuditLog.objects.filter(action='student.class_level_changed').exists())

    def test_integrity_error_returns_400_without_mutation_or_audit(self):
        self.client.force_login(self.staff)
        with patch('dashboard.views.Profile.save', side_effect=IntegrityError('test')):
            response = self.client.post(
                self.url,
                data=json.dumps({'student_id': self.student.pk, 'class_level': '3'}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 400)
        self.student.profile.refresh_from_db()
        self.assertEqual(self.student.profile.class_level, '1')
        self.assertFalse(AuditLog.objects.filter(action='student.class_level_changed').exists())

    def test_teacher_student_list_does_not_render_class_edit_controls(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse('dashboard:students'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Sınıfını Düzenle')
        self.assertNotContains(response, self.url)

    def test_student_rows_link_to_canonical_slug_profile(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse('dashboard:students'))

        self.assertContains(response, self.student.profile.get_absolute_url())
        self.assertNotContains(response, f'/accounts/profile/{self.student.pk}/')


class UserModerationPermissionTests(TestCase):
    def setUp(self):
        self.target = User.objects.create_user('moderation-target', 'target@example.com', 'StrongPassword123!')
        self.admin = User.objects.create_user('real-admin', 'admin@example.com', 'StrongPassword123!', is_staff=True)
        self.teacher = User.objects.create_user('moderation-teacher', 'teacher@example.com', 'StrongPassword123!')
        self.teacher.profile.user_type = 'teacher'
        self.teacher.profile.save(update_fields=['user_type'])
        self.staff_student = User.objects.create_user('moderation-staff-student', 'staffstudent@example.com', 'StrongPassword123!')
        self.staff_student.profile.user_type = 'staff_student'
        self.staff_student.profile.save(update_fields=['user_type'])

    def test_staff_student_can_suspend_student_but_teacher_and_close_are_denied(self):
        url = reverse('dashboard:moderate_user', args=[self.target.pk])
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(url, {
            'action': 'suspend', 'reason': 'spam', 'description': 'Yetkisiz deneme',
            'expires_at': (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S'),
        }).status_code, 403)
        self.client.force_login(self.staff_student)
        self.assertEqual(self.client.post(url, {
            'action': 'close', 'reason': 'spam', 'description': 'Yetkisiz kapatma',
        }).status_code, 403)
        self.client.post(url, {
            'action': 'suspend', 'reason': 'spam', 'description': 'Spam incelemesi',
            'expires_at': (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S'),
        })
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)

    def test_real_admin_can_suspend_with_reason_and_audit_log(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('dashboard:moderate_user', args=[self.target.pk]), {
            'action': 'suspend', 'reason': 'spam', 'description': 'Spam incelemesi',
            'expires_at': (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:%S'),
        })
        self.assertRedirects(response, reverse('dashboard:moderation_user_detail', args=[self.target.pk]))
        self.target.refresh_from_db()
        self.target.profile.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertEqual(self.target.profile.account_status, 'suspended')
        action = UserModerationAction.objects.get(user=self.target)
        self.assertEqual(action.reason, 'spam')
        self.assertEqual(action.description, 'Spam incelemesi')
        self.assertTrue(AuditLog.objects.filter(action='user.suspend', target_id=str(self.target.pk)).exists())

    def test_moderation_page_never_displays_password_or_verification_code(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('dashboard:moderation_user_detail', args=[self.target.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dashboard-shell')
        self.assertContains(response, 'Kullanıcı Moderasyonu')
        self.assertNotContains(response, self.target.password)
        self.assertContains(response, 'Parola ve doğrulama kodları bu ekranda gösterilmez')

    def test_moderation_list_uses_dashboard_shell(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('dashboard:moderation_users'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dashboard-shell')
        self.assertContains(response, 'Kullanıcı moderasyonu')

    def test_only_admin_can_promote_student_to_bst_authority_and_group_is_synced(self):
        url = reverse('dashboard:change_user_role', args=[self.target.pk])
        self.assertEqual(self.client.get(url).status_code, 302)

        self.client.force_login(self.staff_student)
        self.assertEqual(self.client.post(url, {
            'new_role': 'staff_student',
            'description': 'Topluluk içerik yönetimi görevi',
            'confirm_role_change': 'yes',
        }).status_code, 403)

        self.client.force_login(self.admin)
        response = self.client.post(url, {
            'new_role': 'staff_student',
            'description': 'Topluluk içerik yönetimi görevi',
            'confirm_role_change': 'yes',
        })
        self.assertRedirects(response, reverse('dashboard:moderation_user_detail', args=[self.target.pk]))
        self.target.profile.refresh_from_db()
        self.assertEqual(self.target.profile.user_type, 'staff_student')
        self.assertTrue(self.target.groups.filter(name='BST Yetkilisi').exists())
        self.assertTrue(AuditLog.objects.filter(action='user.role_changed', target_id=str(self.target.pk)).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.target, notification_type='moderation').exists())

    def test_role_change_requires_confirmation_and_rejects_non_student_roles(self):
        self.client.force_login(self.admin)
        url = reverse('dashboard:change_user_role', args=[self.target.pk])
        self.client.post(url, {
            'new_role': 'staff_student',
            'description': 'Eksik onay testi',
        })
        self.target.profile.refresh_from_db()
        self.assertEqual(self.target.profile.user_type, 'student')

        self.teacher.profile.user_type = 'teacher'
        self.teacher.profile.save(update_fields=['user_type'])
        teacher_url = reverse('dashboard:change_user_role', args=[self.teacher.pk])
        self.client.post(teacher_url, {
            'new_role': 'staff_student',
            'description': 'Geçersiz rol geçişi',
            'confirm_role_change': 'yes',
        })
        self.teacher.profile.refresh_from_db()
        self.assertEqual(self.teacher.profile.user_type, 'teacher')
