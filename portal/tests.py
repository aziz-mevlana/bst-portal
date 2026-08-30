from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile
from alumni.models import Alumni
from career.models import Opportunity
from projects.models import (
    Project,
    ProjectFeature,
    ProjectRequest,
    ProjectType,
    Team,
    TeamOpenRole,
    Technology,
)


class GlobalSearchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('search-owner', password='StrongPassword123!')
        self.project = Project.objects.create(
            project_type=ProjectType.objects.get(code='INDEPENDENT'),
            title='Akıllı Kampüs Uygulaması',
            description='Kampüs içi dijital çözüm',
            created_by=self.user,
            visibility='public',
            approval_status='approved',
        )
        self.private_project = Project.objects.create(
            project_type=ProjectType.objects.get(code='INDEPENDENT'),
            title='Gizli Kampüs Çalışması',
            created_by=self.user,
            visibility='private',
            approval_status='approved',
        )
        Profile.objects.filter(user=self.user).update(
            headline='Veri bilimi öğrencisi',
            is_portfolio_public=True,
        )
        Alumni.objects.create(full_name='Kampüs Mezunu', is_show_in_alumni_list=True)

    def test_search_exposes_only_public_projects(self):
        response = self.client.get(reverse('portal:global_search'), {'q': 'Kampüs'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.project.title)
        self.assertNotContains(response, self.private_project.title)

    def test_filter_only_search_and_tabs_preserve_selected_filters(self):
        technology = Technology.objects.create(name='Search Technology')
        self.project.technologies.add(technology)
        response = self.client.get(reverse('portal:global_search'), {'technology': technology.pk, 'type': self.project.project_type_id})
        self.assertEqual(response.context['total_visible'], 1)
        self.assertContains(response, self.project.title)
        for tab in response.context['tabs']:
            self.assertIn(f'technology={technology.pk}', tab['url'])
            self.assertIn(f'type={self.project.project_type_id}', tab['url'])
        self.assertEqual(str(response.context['form']['type'].value()), str(self.project.project_type_id))

    def test_bad_filters_are_validation_errors_not_server_errors(self):
        for params in [{'technology': 'abc'}, {'category': '-5'}, {'type': '9' * 70},
                       {'graduation_year': 'abc'}, {'graduation_year': '10000'}, {'availability': 'unknown'}, {'tab': 'bad'}]:
            with self.subTest(params=params):
                response = self.client.get(reverse('portal:global_search'), {'q': 'Kampüs', **params})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)
                self.assertFalse(response.context['sections'])

    def test_full_name_words_can_match_different_fields(self):
        self.user.first_name = 'Ada'
        self.user.last_name = 'Lovelace'
        self.user.save()
        response = self.client.get(reverse('portal:global_search'), {'q': 'Ada Lovelace', 'tab': 'talent'})
        self.assertEqual([p.user_id for p in response.context['result_sets']['talent']], [self.user.pk])

    def test_pagination_keeps_filters_and_uses_full_result_count(self):
        for index in range(14):
            Project.objects.create(title=f'Paging {index:02d}', created_by=self.user,
                project_type=self.project.project_type, visibility='public', approval_status='approved')
        response = self.client.get(reverse('portal:global_search'), {'q': 'Paging', 'tab': 'projects', 'type': self.project.project_type_id, 'page': 2})
        self.assertEqual(response.context['total_visible'], 14)
        self.assertEqual(len(response.context['result_sets']['projects']), 2)
        self.assertIn('tab=projects', response.context['previous_url'])
        self.assertIn(f'type={self.project.project_type_id}', response.context['previous_url'])

    def test_inline_search_respects_privacy_and_does_not_record_each_keystroke(self):
        from core.models import AnalyticsEvent
        before = AnalyticsEvent.objects.count()
        response = self.client.get(reverse('portal:global_search'), {'q': 'Kampüs', 'format': 'json'})
        self.assertEqual(response.status_code, 200)
        urls = [item['url'] for item in response.json()['results']]
        self.assertIn(self.project.get_absolute_url(), urls)
        self.assertNotIn(self.private_project.get_absolute_url(), urls)
        self.assertFalse(any('/alumni/' in url for url in urls))
        self.assertEqual(AnalyticsEvent.objects.count(), before)
        self.assertIn('no-store', response['Cache-Control'])

    def test_inline_search_short_query_and_invalid_filters(self):
        url = reverse('portal:global_search')
        self.assertEqual(self.client.get(url, {'q': 'a', 'format': 'json'}).json()['results'], [])
        self.assertEqual(self.client.get(url, {'q': 'ab', 'format': 'json', 'technology': 'oops'}).status_code, 400)

    def test_inline_search_fills_preview_without_losing_people(self):
        for index in range(10):
            Project.objects.create(title=f'Veri projesi {index}', created_by=self.user,
                project_type=self.project.project_type, visibility='public', approval_status='approved')
        response = self.client.get(reverse('portal:global_search'), {'q': 'Veri', 'format': 'json'})
        results = response.json()['results']
        self.assertEqual(len(results), 8)
        self.assertEqual(response.json()['total'], 11)
        self.assertIn(self.user.profile.get_absolute_url(), [item['url'] for item in results])

    def test_news_tab_only_exposes_published_articles(self):
        from news.models import Article
        published = Article.objects.create(title='Kampüs haberleri', summary='Yayındaki haber', is_approved=True)
        Article.objects.create(title='Kampüs taslak', summary='Taslak haber', is_approved=False)
        future = Article.objects.create(title='Kampüs gelecek haber', summary='Gelecek haber', is_approved=True)
        Article.objects.filter(pk=future.pk).update(date=timezone.now() + timezone.timedelta(days=1))
        response = self.client.get(reverse('portal:global_search'), {'q': 'Kampüs', 'tab': 'news'})
        self.assertEqual(response.context['total_visible'], 1)
        self.assertEqual(response.context['result_sets']['news'], [published])
        self.assertEqual(response.context['result_sets']['projects'], [])

    def test_availability_scope_does_not_include_unrelated_projects(self):
        self.user.profile.is_looking_for_job = True
        self.user.profile.save()
        response = self.client.get(reverse('portal:global_search'), {'availability': 'job'})
        self.assertEqual(response.context['total_visible'], 1)
        self.assertEqual(response.context['result_sets']['projects'], [])

    def test_hidden_class_and_inactive_people_do_not_match_filters(self):
        self.user.profile.show_class_level = False
        self.user.profile.save()
        response = self.client.get(reverse('portal:global_search'), {'class_level': '1'})
        self.assertEqual(response.context['result_sets']['talent'], [])
        self.user.profile.account_status = 'suspended'
        self.user.profile.save()
        response = self.client.get(reverse('portal:global_search'), {'q': 'Veri', 'format': 'json'})
        self.assertEqual(response.json()['results'], [])

    def test_anonymous_search_does_not_expose_alumni(self):
        response = self.client.get(reverse('portal:global_search'), {'q': 'Kampüs Mezunu'})
        alumnus = Alumni.objects.get(full_name='Kampüs Mezunu')
        self.assertNotContains(response, reverse('alumni:alumni_detail_by_id', args=[alumnus.pk]))

    def test_bst_authority_keeps_public_student_portfolio(self):
        self.user.profile.user_type = 'staff_student'
        self.user.profile.is_portfolio_public = True
        self.user.profile.save(update_fields=['user_type', 'is_portfolio_public'])

        response = self.client.get(
            reverse('portal:portfolio_detail', args=[self.user.profile.public_slug])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'BST Yetkilisi')

    def test_public_portfolio_edit_button_opens_project_showcase(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('portal:portfolio_detail', args=[self.user.profile.public_slug])
        )

        self.assertContains(response, reverse('accounts:profile') + '#manage-showcase')
        self.assertNotContains(response, 'Portfolyoyu düzenle')

    def test_superuser_with_legacy_authority_role_is_not_a_public_student_profile(self):
        admin = User.objects.create_superuser(
            'legacy-admin', 'legacy-admin@example.com', 'StrongPassword123!'
        )
        admin.first_name = 'Yönetici'
        admin.last_name = 'Hesabı'
        admin.save(update_fields=['first_name', 'last_name'])
        admin.profile.user_type = 'staff_student'
        admin.profile.is_portfolio_public = True
        admin.profile.show_in_search = True
        admin.profile.save(update_fields=['user_type', 'is_portfolio_public', 'show_in_search'])

        portfolio_url = reverse('portal:portfolio_detail', args=[admin.profile.public_slug])
        self.assertEqual(self.client.get(portfolio_url).status_code, 404)
        self.assertNotContains(self.client.get(reverse('portal:talent_list')), 'Yönetici Hesabı')
        self.assertFalse(admin.groups.filter(name='BST Yetkilisi').exists())


class HomePageCompositionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            'home-owner',
            email='home-owner@example.com',
            password='StrongPassword123!',
            first_name='Ana',
            last_name='Sayfa',
        )
        self.project_type = ProjectType.objects.get(code='INDEPENDENT')

    def test_homepage_exposes_new_editorial_structure_and_institution_anchor(self):
        response = self.client.get(reverse('portal:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'Fikirlerin projeye, projelerin <em>gerçek etkiye</em> dönüştüğü yer.',
            html=True,
        )
        self.assertContains(response, 'BST Akademi ile iş birliği yapın.')
        self.assertContains(response, 'id="kurumlar-icin"')
        self.assertContains(response, 'href="#kurumlar-icin"')
        self.assertContains(response, 'css/homepage.css')
        self.assertContains(response, 'js/homepage.js')

    def test_project_and_career_opportunities_render_as_accessible_tabs(self):
        ProjectRequest.objects.create(
            title='Akıllı şehir proje ekibi',
            project_type=self.project_type,
            status='open',
            teacher=self.user,
            deadline=timezone.localdate() + timezone.timedelta(days=14),
        )
        Opportunity.objects.create(
            title='Yazılım geliştirme stajı',
            opportunity_type='internship',
            organization='BST Teknoloji',
            description='Öğrenciler için uygulamalı geliştirme fırsatı.',
            work_mode='hybrid',
            contact_method='portal',
            deadline=timezone.localdate() + timezone.timedelta(days=21),
            created_by=self.user,
            approval_status='approved',
        )

        response = self.client.get(reverse('portal:index'))

        self.assertContains(response, 'role="tablist"')
        self.assertContains(response, 'id="project-opportunities-tab"')
        self.assertContains(response, 'id="career-opportunities-tab"')
        self.assertContains(response, 'Akıllı şehir proje ekibi')
        self.assertContains(response, 'Yazılım geliştirme stajı')

    def test_featured_project_without_media_uses_technology_aware_abstract_cover(self):
        project = Project.objects.create(
            project_type=self.project_type,
            title='Mobil Sağlık Asistanı',
            description='Mobil sağlık takibi için öğrenci projesi.',
            created_by=self.user,
            visibility='public',
            approval_status='approved',
        )
        mobile_technology = Technology.objects.create(
            name='Homepage Mobile Test',
            group='mobile',
        )
        project.technologies.add(mobile_technology)
        ProjectFeature.objects.create(project=project, is_active=True)

        response = self.client.get(reverse('portal:index'))

        self.assertContains(response, 'home-abstract-cover--coral')
        self.assertContains(
            response,
            'Mobil Sağlık Asistanı için soyut teknoloji görseli',
        )
        self.assertNotContains(response, '<span>M</span>')

    def test_open_team_role_is_integrated_into_homepage_ecosystem(self):
        team = Team.objects.create(
            name='Portal Üretim Ekibi',
            leader=self.user,
            recruitment_open=True,
        )
        TeamOpenRole.objects.create(
            team=team,
            title='Mobil geliştirici',
            is_open=True,
        )

        response = self.client.get(reverse('portal:index'))

        self.assertContains(response, 'Açık ekip rolü')
        self.assertContains(response, 'Mobil geliştirici')
        self.assertContains(response, team.get_absolute_url())
