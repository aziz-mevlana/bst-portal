import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserReport, WebsiteModerationHistory
from alumni.models import Alumni, AlumniRegistrationRequest
from career.models import CollaborationRequest
from core.models import AnalyticsEvent, AuditLog
from news.models import Article, NewsKeyword
from projects.models import Project, ProjectType

from .statistics import dashboard_statistics


class NewsManagementModernizationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('news-manager', password='StrongPassword123!', is_staff=True)
        self.pending = Article.objects.create(title='Bekleyen', summary='Özet', content='İçerik')
        self.approved = Article.objects.create(
            title='Onaylı', summary='Özet', content='İçerik', is_approved=True,
        )
        self.keyword = NewsKeyword.objects.create(keyword='Django')
        self.client.force_login(self.admin)

    def test_single_delete_is_post_only_and_works_for_approved_article(self):
        url = reverse('dashboard:news_delete')
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(
            url, data=json.dumps({'news_id': self.approved.pk}), content_type='application/json',
        )
        self.assertTrue(response.json()['success'])
        self.assertFalse(Article.objects.filter(pk=self.approved.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action='news.deleted').exists())

    def test_bulk_delete_accepts_only_valid_ids_and_preserves_keywords(self):
        invalid = self.client.post(
            reverse('dashboard:news_delete_bulk'),
            data=json.dumps({'ids': ['bad', '', None]}), content_type='application/json',
        )
        self.assertEqual(invalid.status_code, 400)
        response = self.client.post(
            reverse('dashboard:news_delete_bulk'),
            data=json.dumps({'ids': [self.pending.pk, self.approved.pk, 'bad']}),
            content_type='application/json',
        )
        self.assertEqual(response.json()['count'], 2)
        self.assertFalse(Article.objects.exists())
        self.assertTrue(NewsKeyword.objects.filter(pk=self.keyword.pk).exists())


class DashboardStatisticsTests(TestCase):
    def test_kpis_match_central_query_definitions(self):
        admin = User.objects.create_user('stats-admin', is_staff=True)
        student = User.objects.create_user('stats-student')
        student.profile.class_level = '4'
        student.profile.save()
        applicant = User.objects.create_user('stats-alumni', email='stats-alumni@example.com', is_active=False)
        applicant.profile.user_type = 'alumni'
        applicant.profile.class_level = None
        applicant.profile.account_status = 'pending_review'
        applicant.profile.save()
        Alumni.objects.create(full_name='Mevcut Mezun', graduation_year=2020)
        AlumniRegistrationRequest.objects.create(
            user=applicant, full_name='Yeni Mezun', graduation_year=2024,
            email=applicant.email,
        )
        UserReport.objects.create(
            reporter=student, reported_user=admin, reason='other', description='İncelenecek rapor',
        )
        CollaborationRequest.objects.create(
            contact_name='Kişi', organization='Kurum', job_title='Yönetici',
            email='contact@example.com', request_type='other', title='Talep', description='Açıklama',
            consent_accepted=True, email_verified_at=timezone.now(), status='pending_review',
        )
        Project.objects.create(
            project_type=ProjectType.objects.get(code='INDEPENDENT'),
            title='Aktif proje', created_by=student, approval_status='approved',
            development_status='in_progress', visibility='public',
        )
        Project.objects.create(
            project_type=ProjectType.objects.get(code='INDEPENDENT'),
            title='Tamamlanan proje', created_by=student, approval_status='approved',
            development_status='completed', visibility='public',
        )
        stats = dashboard_statistics()
        self.assertEqual(stats['kpis']['active_projects'], 1)
        self.assertEqual(stats['kpis']['completed_projects'], 1)
        self.assertEqual(stats['kpis']['alumni'], 1)
        self.assertEqual(stats['kpis']['pending_alumni'], 1)
        self.assertEqual(stats['kpis']['open_reports'], 1)
        self.assertEqual(stats['kpis']['pending_collaboration'], 1)
        self.assertEqual(
            stats['kpis']['pending_moderation'],
            stats['kpis']['open_reports'] + stats['kpis']['pending_websites']
            + stats['kpis']['pending_alumni'] + stats['kpis']['pending_collaboration'],
        )
        self.assertEqual(
            stats['kpis']['pending_operations'],
            stats['kpis']['pending_moderation'] + stats['kpis']['pending_news'],
        )
        class_four = next(row for row in stats['class_distribution'] if row['key'] == '4')
        self.assertEqual(class_four['count'], 1)

    def test_dashboard_is_compact_translated_and_uses_real_audit_activity(self):
        admin = User.objects.create_user('compact-admin', is_staff=True)
        AuditLog.objects.create(actor=admin, action='project.created')
        AnalyticsEvent.objects.create(
            event_type='ai_answer', visitor_hash='dashboard-visitor',
            succeeded=True, date_bucket=timezone.localdate(),
        )
        self.client.force_login(admin)

        response = self.client.get(reverse('dashboard:home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'AI Asistan Kullanımı')
        self.assertNotContains(response, 'AI_ANSWER')
        self.assertContains(response, 'compact-admin yeni bir proje oluşturdu.')
        self.assertNotContains(response, 'Hızlı Erişim')
        self.assertContains(response, 'Bekleyen İşlemler')
        self.assertContains(response, 'Proje Analitiği')
        self.assertContains(response, 'Yönetim Paneli')
        self.assertNotContains(response, 'Öğrenci Paneli')
        self.assertContains(response, 'static/js/dashboard.js?v=20260830.2')
        self.assertNotContains(response, 'data-mobile-search')
        self.assertEqual(response.content.count(b'data-sidebar-open class='), 1)
        for heading in ('İçerik', 'Kullanıcılar', 'Moderasyon', 'Kurumsal', 'Araçlar'):
            self.assertContains(response, heading)


class DashboardFormLayoutTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('layout-admin', is_staff=True)
        self.client.force_login(self.admin)

    def test_dashboard_filters_use_the_shared_responsive_layout(self):
        for page in ('projects', 'students', 'academics', 'alumni'):
            with self.subTest(page=page):
                response = self.client.get(reverse(f'dashboard:{page}'))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'class="dashboard-filter-form"')
                self.assertContains(response, 'css/bst-ui-v2.css?v=20260830.2')

    def test_color_picker_and_hex_input_have_independent_layout_and_labels(self):
        response = self.client.get(reverse('dashboard:skills'))
        self.assertContains(response, 'class="skill-color-field"')
        self.assertContains(response, 'for="skillName"')
        self.assertContains(response, 'for="skillColorText"')
        self.assertContains(response, 'aria-label="Renk seç"')
        self.assertContains(response, 'aria-label="Renk kodu"')


class StudentCountAndRosterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {}
        for username, role, flags in (
            ('roster-student', 'student', {}),
            ('roster-authority', 'staff_student', {}),
            ('roster-admin', 'student', {'is_staff': True}),
            ('roster-admin-authority', 'staff_student', {'is_staff': True}),
            ('roster-superuser', 'student', {'is_superuser': True}),
            ('roster-superuser-authority', 'staff_student', {'is_superuser': True}),
            ('roster-teacher', 'teacher', {}),
            ('roster-alumni', 'alumni', {}),
        ):
            user = User.objects.create_user(
                username, email=f'{username}@example.com', first_name=username, **flags,
            )
            user.profile.user_type = role
            user.profile.class_level = '2'
            user.profile.save()
            cls.users[username] = user

    def setUp(self):
        self.client.force_login(self.users['roster-admin'])

    def test_student_kpi_includes_authorities_and_excludes_all_admin_accounts(self):
        stats = dashboard_statistics()
        self.assertEqual(stats['kpis']['students'], 2)
        self.assertEqual(stats['kpis']['bst_authorities'], 1)
        self.assertEqual(sum(row['count'] for row in stats['class_distribution']), 2)
        response = self.client.get(reverse('dashboard:home'))
        self.assertEqual(response.context['total_students'], 2)
        self.assertEqual(response.context['kpis']['students'], 2)

    def test_student_list_includes_authorities_and_excludes_all_admin_accounts(self):
        response = self.client.get(reverse('dashboard:students'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 2)
        self.assertSetEqual(
            {user.username for user in response.context['students']},
            {'roster-student', 'roster-authority'},
        )

    def test_authority_remains_in_search_and_class_filters(self):
        filters = {'q': 'roster-authority', 'class_level': '2'}
        response = self.client.get(reverse('dashboard:students'), filters)
        self.assertEqual(response.context['total_count'], 1)
        self.assertEqual(response.context['students'][0], self.users['roster-authority'])
        page = self.client.get(reverse('dashboard:students_load_more'), filters).json()
        self.assertIn(self.users['roster-authority'].email, page['items'])
        self.assertFalse(page['has_more'])

    @patch('dashboard.views.DASHBOARD_PAGE_SIZE', 1)
    def test_pagination_uses_the_same_student_population(self):
        first = self.client.get(reverse('dashboard:students'))
        self.assertEqual(first.context['total_count'], 2)
        self.assertTrue(first.context['has_more'])
        self.assertEqual(first.context['students'][0], self.users['roster-student'])
        more = self.client.get(
            reverse('dashboard:students_load_more'), {'offset': first.context['next_offset']},
        ).json()
        self.assertIn(self.users['roster-authority'].email, more['items'])
        self.assertNotIn(self.users['roster-student'].email, more['items'])
        for username, user in self.users.items():
            if user.is_staff or user.is_superuser:
                self.assertNotIn(user.email, more['items'])
        self.assertFalse(more['has_more'])


class WebsiteModerationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('website-admin', is_staff=True)
        self.owner = User.objects.create_user('website-owner')
        self.owner.profile.website_url = 'https://portfolio.example.com'
        self.owner.profile.website_status = 'pending'
        self.owner.profile.save()
        self.client.force_login(self.admin)

    def test_rejection_requires_standard_reason_and_description(self):
        url = reverse('dashboard:website_review', args=[self.owner.profile.pk])
        self.client.post(url, {'decision': 'reject'})
        self.owner.profile.refresh_from_db()
        self.assertEqual(self.owner.profile.website_status, 'pending')
        self.client.post(url, {
            'decision': 'reject', 'reason': 'security_concern',
            'description': 'Bağlantı güvenli biçimde doğrulanamadı.',
        })
        self.owner.profile.refresh_from_db()
        self.assertEqual(self.owner.profile.website_status, 'rejected')
        history = WebsiteModerationHistory.objects.get(profile=self.owner.profile)
        self.assertEqual(history.reason, 'security_concern')
        self.assertTrue(self.owner.notifications.filter(notification_type='website_review').exists())
        self.assertTrue(AuditLog.objects.filter(action='profile.website_rejected').exists())

    def test_approve_is_post_only_and_makes_public_accessor_available(self):
        url = reverse('dashboard:website_review', args=[self.owner.profile.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url, {'decision': 'approve', 'description': 'İncelendi.'})
        self.owner.profile.refresh_from_db()
        self.assertEqual(self.owner.profile.approved_website_url, 'https://portfolio.example.com')
