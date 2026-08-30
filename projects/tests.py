from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog

from .forms import ProjectCommentForm, ProjectForm
from .models import (
    Project,
    ProjectCaseStudy,
    ProjectCategory,
    ProjectComment,
    ProjectMedia,
    ProjectProgram,
    ProjectRequest,
    ProjectRequestApplication,
    ProjectRepository,
    ProjectSave,
    ProjectType,
    ProjectView,
    ProjectWritingSuggestion,
    Technology, ProjectLike,
)
from .services import accept_project_request_application


def make_user(username, user_type='student'):
    user = User.objects.create_user(username, f'{username}@example.com', 'StrongPassword123!')
    user.profile.user_type = user_type
    user.profile.save(update_fields=['user_type'])
    return user


class ProjectPermissionTests(TestCase):
    def setUp(self):
        self.owner = make_user('owner')
        self.outsider = make_user('outsider')
        project_type = ProjectType.objects.get(code='INDEPENDENT')
        self.project = Project.objects.create(
            project_type=project_type,
            title='Gizli proje',
            created_by=self.owner,
            is_private=True,
            visibility='private',
            approval_status='approved',
            development_status='in_progress',
            status='in_progress',
        )
        self.project.team.add(self.owner)

    def test_outsider_cannot_comment_on_private_project(self):
        self.client.force_login(self.outsider)
        response = self.client.post(
            reverse('projects:add_comment', args=[self.project.id]),
            {'content': 'Görmemem gereken yorum'},
        )
        self.assertRedirects(response, reverse('projects:project_list'))
        self.assertFalse(ProjectComment.objects.exists())

    def test_comment_owner_can_delete_with_post_only(self):
        comment = ProjectComment.objects.create(
            project=self.project,
            author=self.owner,
            content='Silinecek yorum',
        )
        self.client.force_login(self.owner)
        url = reverse('projects:delete_comment', args=[comment.id])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        self.assertFalse(ProjectComment.objects.filter(pk=comment.pk).exists())

    def test_bst_authority_cannot_manage_private_project_or_delete_others_comment(self):
        authority = make_user('limited-authority', 'staff_student')
        comment = ProjectComment.objects.create(
            project=self.project,
            author=self.owner,
            content='Yalnız admin tarafından silinebilir',
        )
        self.client.force_login(authority)

        self.assertRedirects(
            self.client.get(reverse('projects:project_detail', args=[self.project.pk])),
            reverse('projects:project_list'),
        )
        self.client.post(reverse('projects:delete_comment', args=[comment.pk]))
        self.assertTrue(ProjectComment.objects.filter(pk=comment.pk).exists())

    def test_comment_form_rejects_blank_and_overlong_content(self):
        self.assertFalse(ProjectCommentForm({'content': '  '}).is_valid())
        self.assertFalse(ProjectCommentForm({'content': 'a' * 2001}).is_valid())
        self.assertTrue(ProjectCommentForm({'content': 'Yapıcı bir geri bildirim.'}).is_valid())

    def test_comment_and_reply_names_and_avatars_link_to_student_profiles(self):
        self.project.visibility = 'public'
        self.project.is_private = False
        self.project.save()
        self.outsider.profile.user_type = 'staff_student'
        self.outsider.profile.save()
        parent = ProjectComment.objects.create(project=self.project, author=self.owner, content='Ana yorum')
        reply = ProjectComment.objects.create(project=self.project, author=self.outsider, parent=parent, content='Yetkili öğrenci yanıtı')
        page = self.client.get(self.project.get_absolute_url()).content.decode()
        for comment in [parent, reply]:
            with self.subTest(comment=comment.pk):
                card = page.split(f'id="comment-{comment.pk}"', 1)[1].split('</article>', 1)[0]
                profile_url = comment.author.profile.get_absolute_url()
                self.assertEqual(card.count(f'href="{profile_url}"'), 2)
                self.assertEqual(self.client.get(profile_url).status_code, 200)

    def test_comment_private_profile_is_not_linked_for_other_people(self):
        parent = ProjectComment.objects.create(project=self.project, author=self.outsider, content='Gizli portfolyo')
        self.outsider.profile.is_portfolio_public = False
        self.outsider.profile.save()
        self.client.force_login(self.owner)
        page = self.client.get(self.project.get_absolute_url()).content.decode()
        card = page.split(f'id="comment-{parent.pk}"', 1)[1].split('</article>', 1)[0]
        self.assertNotIn(f'href="{self.outsider.profile.get_absolute_url()}"', card)
        self.assertIn('outsider', card)

    def test_admin_comments_do_not_link_to_viewers_own_account(self):
        admin = User.objects.create_superuser('comment-admin', 'comment-admin@example.com', 'StrongPassword123!')
        parent = ProjectComment.objects.create(project=self.project, author=admin, content='Yönetici yorumu')
        self.client.force_login(self.owner)
        page = self.client.get(self.project.get_absolute_url()).content.decode()
        card = page.split(f'id="comment-{parent.pk}"', 1)[1].split('</article>', 1)[0]
        self.assertNotIn('comment-profile-link', card)
        self.assertNotIn(f'href="{reverse("accounts:profile")}"', card)

    def test_teacher_and_alumni_comment_links_use_their_actual_destinations(self):
        from alumni.models import Alumni
        teacher = make_user('comment-teacher', 'teacher')
        graduate = make_user('comment-graduate', 'alumni')
        Alumni.objects.create(user=graduate, is_show_in_alumni_list=True)
        teacher_comment = ProjectComment.objects.create(project=self.project, author=teacher, content='Akademisyen yorumu')
        graduate_comment = ProjectComment.objects.create(project=self.project, author=graduate, content='Mezun yorumu')
        self.client.force_login(self.owner)
        page = self.client.get(self.project.get_absolute_url()).content.decode()
        expected = {
            teacher_comment.pk: f'{reverse("portal:academic_list")}#academic-{teacher.profile.pk}',
            graduate_comment.pk: reverse('alumni:alumni_detail', args=[graduate.username]),
        }
        for pk, url in expected.items():
            card = page.split(f'id="comment-{pk}"', 1)[1].split('</article>', 1)[0]
            self.assertEqual(card.count(f'href="{url}"'), 2)
            self.assertEqual(self.client.get(url.split('#')[0]).status_code, 200)

    def test_inactive_comment_author_has_no_profile_link(self):
        self.outsider.is_active = False
        self.outsider.save()
        parent = ProjectComment.objects.create(project=self.project, author=self.outsider, content='Eski yorum')
        self.client.force_login(self.owner)
        page = self.client.get(self.project.get_absolute_url()).content.decode()
        card = page.split(f'id="comment-{parent.pk}"', 1)[1].split('</article>', 1)[0]
        self.assertNotIn('comment-profile-link', card)

    def test_reply_renders_under_parent_and_notifies_comment_author(self):
        from core.models import Notification
        self.project.visibility = 'public'
        self.project.is_private = False
        self.project.save()
        parent = ProjectComment.objects.create(project=self.project, author=self.outsider, content='Ana yorum')
        self.client.force_login(self.owner)
        response = self.client.post(reverse('projects:add_comment', args=[self.project.pk]), {'content': 'Yanıt <script>test</script>', 'parent_id': parent.pk})
        reply = ProjectComment.objects.get(parent=parent)
        self.assertRedirects(response, f'{self.project.get_absolute_url()}#comment-{reply.pk}')
        notification = Notification.objects.get(recipient=self.outsider, notification_type='project_comment')
        self.assertTrue(notification.target_url.endswith(f'#comment-{reply.pk}'))
        self.assertFalse(Notification.objects.filter(recipient=self.owner).exists())
        page = self.client.get(self.project.get_absolute_url())
        self.assertContains(page, f'id="comment-{reply.pk}"', count=1)
        self.assertContains(page, '2 yorum ve yanıt')
        self.assertContains(page, 'Yanıt &lt;script&gt;test&lt;/script&gt;')
        self.assertContains(page, 'class="comment-replies"')

    def test_reply_rejects_foreign_nested_and_invalid_parent(self):
        other = Project.objects.create(title='Başka proje', created_by=self.owner, project_type=self.project.project_type)
        foreign = ProjectComment.objects.create(project=other, author=self.owner, content='Başka yorum')
        parent = ProjectComment.objects.create(project=self.project, author=self.owner, content='Ana yorum')
        child = ProjectComment.objects.create(project=self.project, parent=parent, author=self.owner, content='Yanıt')
        self.client.force_login(self.owner)
        before = ProjectComment.objects.count()
        for value in [foreign.pk, child.pk, 'bad', '9' * 80, -1]:
            with self.subTest(parent=value):
                response = self.client.post(reverse('projects:add_comment', args=[self.project.pk]), {'content': 'Yeni yanıt', 'parent_id': value})
                self.assertEqual(response.status_code, 404)
        self.assertEqual(ProjectComment.objects.count(), before)

    def test_deleting_root_preserves_other_users_replies(self):
        parent = ProjectComment.objects.create(project=self.project, author=self.owner, content='Ana yorum')
        child = ProjectComment.objects.create(project=self.project, parent=parent, author=self.outsider, content='Korunan yanıt')
        self.client.force_login(self.owner)
        self.client.post(reverse('projects:delete_comment', args=[parent.pk]))
        child.refresh_from_db()
        self.assertIsNone(child.parent_id)

    def test_reply_requires_project_access_and_active_account(self):
        parent = ProjectComment.objects.create(project=self.project, author=self.owner, content='Ana yorum')
        url = reverse('projects:add_comment', args=[self.project.pk])
        payload = {'content': 'Yanıt denemesi', 'parent_id': parent.pk}
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.client.force_login(self.outsider)
        self.client.post(url, payload)
        self.assertFalse(parent.replies.exists())
        self.client.force_login(self.owner)
        self.owner.profile.account_status = 'suspended'
        self.owner.profile.save()
        self.assertEqual(self.client.post(url, payload).status_code, 403)
        self.assertFalse(parent.replies.exists())

    def test_public_project_view_is_counted_once_per_session_per_day(self):
        self.project.visibility = 'public'
        self.project.is_private = False
        self.project.save(update_fields=['visibility', 'is_private'])
        url = reverse('projects:project_detail', args=[self.project.pk])
        self.client.get(url)
        self.client.get(url)
        self.assertEqual(ProjectView.objects.filter(project=self.project).count(), 1)

    def test_public_slug_url_has_canonical_metadata(self):
        self.project.visibility = 'public'
        self.project.is_private = False
        self.project.save(update_fields=['visibility', 'is_private'])
        response = self.client.get(self.project.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.project.get_absolute_url())
        self.assertContains(response, 'content="index,follow"')

    def test_private_project_is_not_in_sitemap(self):
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.project.get_absolute_url())

    def test_save_toggle_is_post_only(self):
        self.project.visibility = 'public'
        self.project.is_private = False
        self.project.save(update_fields=['visibility', 'is_private'])
        self.client.force_login(self.outsider)
        url = reverse('projects:toggle_project_save', args=[self.project.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        self.assertTrue(ProjectSave.objects.filter(project=self.project, user=self.outsider).exists())
        self.client.post(url)
        self.assertFalse(ProjectSave.objects.filter(project=self.project, user=self.outsider).exists())

    def test_outsider_cannot_manage_showcase(self):
        self.client.force_login(self.outsider)
        response = self.client.get(reverse('projects:project_showcase_manage', args=[self.project.pk]))
        self.assertEqual(response.status_code, 403)

    def test_owner_can_open_showcase_management(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('projects:project_showcase_manage', args=[self.project.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('achievement_form', response.context)

    def test_owner_can_delete_own_project_with_explicit_confirmation(self):
        self.client.force_login(self.owner)
        project_pk = self.project.pk
        response = self.client.post(
            reverse('projects:project_delete', args=[project_pk]),
            {'confirm_delete': 'yes'},
        )
        self.assertRedirects(response, reverse('projects:project_list'))
        self.assertFalse(Project.objects.filter(pk=project_pk).exists())
        self.assertTrue(
            AuditLog.objects.filter(
                action='project.deleted',
                target_id=str(project_pk),
            ).exists()
        )

    def test_project_delete_rejects_get_missing_confirmation_and_outsider(self):
        url = reverse('projects:project_delete', args=[self.project.pk])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        self.assertTrue(Project.objects.filter(pk=self.project.pk).exists())

        self.client.force_login(self.outsider)
        self.assertEqual(
            self.client.post(url, {'confirm_delete': 'yes'}).status_code,
            403,
        )
        self.assertTrue(Project.objects.filter(pk=self.project.pk).exists())


class ProjectTaxonomyTests(TestCase):
    def test_seed_data_exists(self):
        self.assertEqual(ProjectType.objects.count(), 7)
        self.assertEqual(ProjectProgram.objects.count(), 3)
        self.assertTrue(ProjectType.objects.filter(code='CAPSTONE').exists())
        self.assertTrue(ProjectProgram.objects.filter(slug='teknofest').exists())

    def test_project_type_code_is_immutable_and_delete_is_soft(self):
        project_type = ProjectType.objects.get(code='INDEPENDENT')
        project_type.code = 'CHANGED'
        with self.assertRaises(ValidationError):
            project_type.save()
        project_type.refresh_from_db()
        project_type.delete()
        project_type.refresh_from_db()
        self.assertFalse(project_type.is_active)

    def test_normal_form_does_not_offer_system_sources(self):
        choices = dict(ProjectForm().fields['creation_source'].choices)
        self.assertNotIn('ACADEMIC_REQUEST', choices)
        self.assertNotIn('LEGACY', choices)
        self.assertIn('STUDENT_IDEA', choices)

    def test_seed_taxonomy_is_idempotent(self):
        call_command('seed_taxonomy')
        technology_count = Technology.objects.count()
        category_count = ProjectCategory.objects.count()
        call_command('seed_taxonomy')
        self.assertEqual(Technology.objects.count(), technology_count)
        self.assertEqual(ProjectCategory.objects.count(), category_count)
        self.assertTrue(Technology.objects.filter(name='Django', group='backend', is_active=True).exists())
        self.assertTrue(ProjectCategory.objects.filter(name='Siber Güvenlik', is_active=True).exists())

    def test_safe_alias_merge_preserves_project_relation(self):
        call_command('seed_taxonomy')
        owner = make_user('taxonomy-owner')
        project = Project.objects.create(
            project_type=ProjectType.objects.get(code='INDEPENDENT'),
            title='React projesi', created_by=owner,
        )
        duplicate = Technology.objects.create(name='React.js')
        project.technologies.add(duplicate)
        call_command('seed_taxonomy', merge_safe=True)
        duplicate.refresh_from_db()
        canonical = Technology.objects.get(name='React')
        self.assertFalse(duplicate.is_active)
        self.assertTrue(project.technologies.filter(pk=canonical.pk).exists())

    def test_inactive_taxonomy_is_hidden_from_new_project_form(self):
        inactive = Technology.objects.create(name='Eski Teknoloji', is_active=False)
        self.assertNotIn(inactive, ProjectForm().fields['technologies'].queryset)


class ProjectFormAndNavigationTests(TestCase):
    def setUp(self):
        self.owner = make_user('form-owner')
        self.member = make_user('form-member')
        self.inactive = make_user('inactive-member')
        self.inactive.is_active = False
        self.inactive.save(update_fields=['is_active'])
        self.teacher = make_user('form-teacher', 'teacher')
        self.project_type = ProjectType.objects.get(code='INDEPENDENT')

    def test_critical_project_labels_are_turkish(self):
        form = ProjectForm(current_user=self.owner)
        self.assertEqual(form.fields['project_type'].label, 'Proje türü')
        self.assertEqual(form.fields['creation_source'].label, 'Projenin kaynağı')
        self.assertEqual(form.fields['team'].label, 'Takım üyeleri')
        self.assertEqual(form.fields['visibility'].label, 'Görünürlük')

    def test_required_select_prompts_cannot_be_saved(self):
        form = ProjectForm(data={
            'project_type': '',
            'creation_source': '',
            'title': 'Seçimsiz proje',
            'development_status': '',
            'visibility': '',
        }, current_user=self.owner)

        self.assertFalse(form.is_valid())
        for field_name in ('project_type', 'creation_source', 'development_status', 'visibility'):
            self.assertIn(field_name, form.errors)
            self.assertTrue(form.fields[field_name].required)
            self.assertTrue(form.fields[field_name].widget.attrs['required'])

    def test_project_text_fields_have_explanatory_placeholders(self):
        form = ProjectForm(current_user=self.owner)

        for field_name in ('title', 'description', 'expected_output', 'project_link'):
            self.assertTrue(form.fields[field_name].widget.attrs.get('placeholder'))

    def test_team_search_returns_only_public_fields_and_active_students(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('projects:team_member_search'), {'q': 'form'})
        self.assertEqual(response.status_code, 200)
        payload = response.json()['results']
        ids = {item['id'] for item in payload}
        self.assertIn(self.member.pk, ids)
        self.assertNotIn(self.owner.pk, ids)
        self.assertNotIn(self.inactive.pk, ids)
        self.assertNotIn(self.teacher.pk, ids)
        self.assertTrue(all('email' not in item and 'phone' not in item for item in payload))

    def test_owner_cannot_be_added_to_team_and_selection_survives_error(self):
        form = ProjectForm(data={
            'project_type': self.project_type.pk, 'creation_source': 'STUDENT_IDEA',
            'title': '', 'description': 'Açıklama', 'team': [self.member.pk],
            'development_status': 'idea', 'visibility': 'private',
        }, current_user=self.owner)
        self.assertFalse(form.is_valid())
        self.assertIn(self.member.pk, form['team'].value())
        owner_form = ProjectForm(data={
            'project_type': self.project_type.pk, 'creation_source': 'STUDENT_IDEA',
            'title': 'Proje', 'team': [self.owner.pk],
            'development_status': 'idea', 'visibility': 'private',
        }, current_user=self.owner)
        self.assertFalse(owner_form.is_valid())

    def test_public_can_reach_project_showcase_and_open_announcements(self):
        announcement = ProjectRequest.objects.create(
            title='Public proje ilanı', project_type=self.project_type,
            teacher=self.teacher, status='open', description='Herkese açık ilan',
        )
        list_response = self.client.get(reverse('projects:request_list'))
        self.assertContains(list_response, announcement.title)
        self.assertContains(list_response, 'Proje Vitrini')
        self.assertContains(list_response, 'İlanlar')
        self.assertNotContains(list_response, 'Kaydedilenler')
        self.assertEqual(self.client.get(reverse('projects:request_detail', args=[announcement.pk])).status_code, 200)

    def test_role_based_project_tabs(self):
        self.client.force_login(self.owner)
        student_page = self.client.get(reverse('projects:project_list'))
        self.assertContains(student_page, 'Kaydedilenler')
        self.assertContains(student_page, 'Yeni Proje')
        self.assertNotContains(student_page, 'Başvurularım')
        self.assertNotContains(student_page, 'Gelen Başvurular')
        self.client.force_login(self.teacher)
        teacher_page = self.client.get(reverse('projects:project_list'))
        self.assertContains(teacher_page, 'Kaydedilenler')
        self.assertContains(teacher_page, 'Yeni Proje')
        self.assertNotContains(teacher_page, 'İlanlarım')
        self.assertNotContains(teacher_page, 'Gelen Başvurular')

    def test_pending_email_account_cannot_create_project(self):
        self.owner.profile.account_status = 'pending_email'
        self.owner.profile.save(update_fields=['account_status'])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('projects:project_create')).status_code, 403)

    def test_video_media_rejects_untrusted_provider(self):
        owner = make_user('media-owner')
        project = Project.objects.create(
            project_type=ProjectType.objects.get(code='INDEPENDENT'),
            title='Medya projesi',
            created_by=owner,
        )
        media = ProjectMedia(
            project=project,
            media_type='video',
            external_url='https://example.com/untrusted-video',
        )
        with self.assertRaises(ValidationError):
            media.full_clean()


class RepositoryAndMediaTests(TestCase):
    def setUp(self):
        self.owner = make_user('github-owner')
        self.project = Project.objects.create(
            project_type=ProjectType.objects.get(code='INDEPENDENT'),
            title='GitHub bağlantılı proje',
            created_by=self.owner,
            visibility='public',
            approval_status='approved',
        )

    def test_only_repository_path_is_accepted(self):
        with self.assertRaises(ValidationError):
            ProjectRepository.objects.create(
                project=self.project,
                repository_path='https://evil.example/repo',
            )
        repository = ProjectRepository.objects.create(
            project=self.project,
            repository_path='BST-Portal/project',
        )
        self.assertEqual(repository.owner, 'BST-Portal')
        self.assertEqual(repository.name, 'project')
        self.assertEqual(repository.repository_url, 'https://github.com/BST-Portal/project')

    def test_github_sync_endpoint_is_removed(self):
        with self.assertRaises(Exception):
            reverse('projects:project_repository_sync', args=[self.project.pk])

    def test_demo_link_uses_warning_page_without_case_study(self):
        from core.models import AnalyticsEvent
        self.project.project_link = 'https://example.com/app?mode=demo'
        self.project.save()
        self.assertFalse(ProjectCaseStudy.objects.filter(project=self.project).exists())
        url = reverse('projects:project_external_redirect', args=[self.project.pk, 'demo'])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.project.project_link)
        self.assertContains(response, 'BST Portal\'dan ayrılıyorsunuz')
        self.assertNotIn('Location', response)
        self.assertTrue(AnalyticsEvent.objects.filter(event_type='demo_click', target_id=str(self.project.pk)).exists())

    def test_demo_redirect_prefers_demo_and_falls_back_when_blank(self):
        self.project.project_link = 'https://example.com/project'
        self.project.save()
        case_study = ProjectCaseStudy.objects.create(project=self.project, demo_url='https://example.com/demo')
        url = reverse('projects:project_external_redirect', args=[self.project.pk, 'demo'])
        self.assertContains(self.client.get(url), case_study.demo_url)
        case_study.demo_url = ''
        case_study.save()
        self.assertContains(self.client.get(url), self.project.project_link)

    def test_missing_demo_returns_404_and_private_demo_is_not_exposed(self):
        url = reverse('projects:project_external_redirect', args=[self.project.pk, 'demo'])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.project.project_link = 'https://example.com/private-demo'
        self.project.visibility = 'private'
        self.project.is_private = True
        self.project.save()
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(url), self.project.project_link)

    def test_github_redirect_also_works_without_case_study(self):
        repository = ProjectRepository.objects.create(project=self.project, repository_path='BST-Portal/project')
        response = self.client.get(reverse('projects:project_external_redirect', args=[self.project.pk, 'github']))
        self.assertContains(response, repository.repository_url)

    def test_like_toggle_is_unique_and_reversible(self):
        viewer = make_user('like-viewer')
        self.client.force_login(viewer)
        url = reverse('projects:toggle_project_like', args=[self.project.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        self.assertEqual(ProjectLike.objects.filter(project=self.project, user=viewer).count(), 1)
        self.client.post(url)
        self.assertFalse(ProjectLike.objects.filter(project=self.project, user=viewer).exists())

    def test_media_rejects_spoofed_file_extension(self):
        owner = make_user('spoof-owner')
        project = Project.objects.create(
            project_type=ProjectType.objects.get(code='INDEPENDENT'),
            title='Dosya doğrulama projesi',
            created_by=owner,
        )
        media = ProjectMedia(
            project=project,
            media_type='image',
            file=SimpleUploadedFile('fake.png', b'<script>alert(1)</script>', content_type='image/png'),
        )
        with self.assertRaises(ValidationError):
            media.full_clean()


class ProjectRequestApplicationTests(TestCase):
    def setUp(self):
        self.teacher = make_user('teacher', 'teacher')
        self.student = make_user('student1')
        self.other_student = make_user('student2')
        self.outsider_teacher = make_user('teacher2', 'teacher')
        self.project_type = ProjectType.objects.get(code='RESEARCH')
        self.category = ProjectCategory.objects.create(name='Yapay Zeka')
        self.technology = Technology.objects.create(name='Python')
        self.project_request = ProjectRequest.objects.create(
            title='Akıllı kampüs asistanı',
            project_type=self.project_type,
            teacher=self.teacher,
            description='Kampüs bilgi asistanı geliştirilecek.',
            expected_output='Çalışan bir web uygulaması',
            status='open',
            deadline=timezone.now().date() + timedelta(days=10),
        )
        self.project_request.categories.add(self.category)
        self.project_request.technologies.add(self.technology)

    def make_application(self, student=None):
        return ProjectRequestApplication.objects.create(
            project_request=self.project_request,
            student=student or self.student,
            motivation='Bu konuda deneyim sahibiyim.',
            proposed_approach='Önce gereksinimleri analiz edeceğim.',
        )

    def test_student_can_apply_once_and_apply_is_post_only(self):
        self.client.force_login(self.student)
        url = reverse('projects:request_apply', args=[self.project_request.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        payload = {'motivation': 'Katılmak istiyorum.', 'proposed_approach': 'Prototip ile başlayacağım.'}
        self.client.post(url, payload)
        self.client.post(url, payload)
        self.assertEqual(
            ProjectRequestApplication.objects.filter(
                project_request=self.project_request,
                student=self.student,
            ).count(),
            1,
        )

    def test_student_cannot_see_another_students_applications(self):
        self.make_application()
        self.client.force_login(self.other_student)
        response = self.client.get(reverse('projects:request_applications', args=[self.project_request.pk]))
        self.assertEqual(response.status_code, 403)

    def test_only_owner_academic_can_manage_applications(self):
        self.make_application()
        self.client.force_login(self.outsider_teacher)
        response = self.client.get(reverse('projects:request_applications', args=[self.project_request.pk]))
        self.assertEqual(response.status_code, 403)

    def test_student_can_only_withdraw_own_pending_application(self):
        application = self.make_application()
        self.client.force_login(self.student)
        url = reverse('projects:request_application_withdraw', args=[application.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        application.refresh_from_db()
        self.assertEqual(application.status, 'withdrawn')
        self.assertIsNotNone(application.withdrawn_at)

    def test_staff_admin_can_delete_request_and_preserve_linked_project(self):
        self.make_application()
        linked_project = Project.objects.create(
            project_request=self.project_request,
            project_type=self.project_type,
            title='Korunacak ilan projesi',
            created_by=self.student,
        )
        admin = User.objects.create_user(
            'request-admin', 'request-admin@example.com', 'StrongPassword123!', is_staff=True
        )
        self.client.force_login(admin)
        list_response = self.client.get(reverse('projects:request_list'))
        self.assertContains(list_response, self.project_request.title)
        url = reverse('projects:request_delete', args=[self.project_request.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        self.assertTrue(ProjectRequest.objects.filter(pk=self.project_request.pk).exists())
        self.client.post(url, {'confirm_delete': 'yes'})
        self.assertFalse(ProjectRequest.objects.filter(pk=self.project_request.pk).exists())
        linked_project.refresh_from_db()
        self.assertIsNone(linked_project.project_request_id)
        self.assertTrue(AuditLog.objects.filter(action='project_request.deleted').exists())

    def test_accept_is_atomic_idempotent_and_creates_one_project(self):
        accepted = self.make_application()
        rejected = self.make_application(self.other_student)

        project, created = accept_project_request_application(
            application_id=accepted.pk,
            reviewer=self.teacher,
            review_note='Uygun bulundu.',
        )
        self.assertTrue(created)
        self.assertEqual(Project.objects.count(), 1)
        self.assertEqual(project.created_by, self.student)
        self.assertEqual(project.advisor, self.teacher)
        self.assertEqual(project.creation_source, 'ACADEMIC_REQUEST')
        self.assertEqual(project.project_type, self.project_type)
        self.assertEqual(project.approval_status, 'approved')
        self.assertEqual(project.development_status, 'idea')
        self.assertEqual(project.visibility, 'private')
        self.assertEqual(project.expected_output, self.project_request.expected_output)
        self.assertTrue(project.team.filter(pk=self.student.pk).exists())
        self.assertTrue(project.categories.filter(pk=self.category.pk).exists())
        self.assertTrue(project.technologies.filter(pk=self.technology.pk).exists())

        self.project_request.refresh_from_db()
        accepted.refresh_from_db()
        rejected.refresh_from_db()
        self.assertEqual(self.project_request.status, 'student_selected')
        self.assertEqual(self.project_request.created_project, project)
        self.assertEqual(accepted.status, 'accepted')
        self.assertEqual(rejected.status, 'rejected')

        same_project, created_again = accept_project_request_application(
            application_id=accepted.pk,
            reviewer=self.teacher,
        )
        self.assertFalse(created_again)
        self.assertEqual(same_project, project)
        self.assertEqual(Project.objects.count(), 1)

    def test_unauthorized_teacher_cannot_accept(self):
        application = self.make_application()
        with self.assertRaises(PermissionDenied):
            accept_project_request_application(
                application_id=application.pk,
                reviewer=self.outsider_teacher,
            )
        self.assertFalse(Project.objects.exists())


class ProjectWritingAssistantTests(TestCase):
    def setUp(self):
        self.owner = make_user('writer-owner')
        self.outsider = make_user('writer-outsider')
        self.project = Project.objects.create(
            project_type=ProjectType.objects.get(code='INDEPENDENT'),
            title='Akıllı Kampüs',
            description='Kampüsteki enerji kullanımını sensörlerle takip eden bir uygulama geliştiriyoruz.',
            created_by=self.owner,
            visibility='private',
        )

    @patch('ai_assistant.project_writing.generate_project_writing_suggestion')
    def test_generation_only_creates_preview(self, generate):
        generate.return_value = {
            'problem': 'Enerji tüketimi görünür değil.',
            'solution': 'Sensör verileri panelde gösterilir.',
            'architecture': 'Django ve MQTT.',
            'technologies': ['Django', 'MQTT'],
            'measurable_results': '',
            'future_developments': 'Tahminleme modülü.',
        }
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('projects:project_writing_generate', args=[self.project.pk]),
            {'source_text': self.project.description},
        )
        suggestion = ProjectWritingSuggestion.objects.get(project=self.project)
        self.assertRedirects(
            response,
            f'{reverse("projects:project_showcase_manage", args=[self.project.pk])}?suggestion={suggestion.pk}#ai-writing',
            fetch_redirect_response=False,
        )
        self.assertEqual(suggestion.status, 'preview')
        self.assertFalse(ProjectCaseStudy.objects.filter(project=self.project).exists())
        self.project.refresh_from_db()
        self.assertEqual(self.project.visibility, 'private')

    def test_only_explicitly_selected_fields_are_applied(self):
        case_study = ProjectCaseStudy.objects.create(project=self.project, solution='Mevcut çözüm')
        suggestion = ProjectWritingSuggestion.objects.create(
            project=self.project,
            created_by=self.owner,
            original_text='Yeterince uzun ham proje metni.',
            suggested_fields={'problem': 'Yeni problem', 'solution': 'Yeni çözüm'},
        )
        self.client.force_login(self.owner)
        self.client.post(
            reverse('projects:project_writing_apply', args=[suggestion.pk]),
            {'fields': ['problem']},
        )
        case_study.refresh_from_db()
        suggestion.refresh_from_db()
        self.project.refresh_from_db()
        self.assertEqual(case_study.problem, 'Yeni problem')
        self.assertEqual(case_study.solution, 'Mevcut çözüm')
        self.assertEqual(suggestion.status, 'applied')
        self.assertEqual(self.project.visibility, 'private')

    def test_outsider_cannot_apply_suggestion(self):
        suggestion = ProjectWritingSuggestion.objects.create(
            project=self.project,
            created_by=self.owner,
            original_text='Yeterince uzun ham proje metni.',
            suggested_fields={'problem': 'Gizli öneri'},
        )
        self.client.force_login(self.outsider)
        response = self.client.post(
            reverse('projects:project_writing_apply', args=[suggestion.pk]),
            {'fields': ['problem']},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ProjectCaseStudy.objects.filter(project=self.project).exists())


class StructuredMatchingTests(TestCase):
    def test_student_matching_uses_public_opt_in_profiles_and_explains_score(self):
        owner = make_user('match-owner')
        candidate = make_user('public-candidate')
        hidden = make_user('hidden-candidate')
        hidden.profile.is_portfolio_public = False
        hidden.profile.save(update_fields=['is_portfolio_public'])
        technology = Technology.objects.create(name='Django Match Tech')
        candidate.profile.technologies.add(technology)
        hidden.profile.technologies.add(technology)
        project = Project.objects.create(
            project_type=ProjectType.objects.get(code='INDEPENDENT'),
            title='Eşleşme projesi',
            created_by=owner,
        )
        project.technologies.add(technology)

        from .matching import rank_student_matches
        matches = rank_student_matches(project)
        self.assertEqual([item['id'] for item in matches], [candidate.pk])
        self.assertEqual(matches[0]['breakdown']['technology'], 40)
        self.assertEqual(matches[0]['breakdown']['availability'], 20)
        self.assertIn('Django Match Tech', matches[0]['matched_technologies'])


class PrivateProjectAuthorizationTests(TestCase):
    def setUp(self):
        self.owner = make_user('private-project-owner')
        self.teacher = make_user('unrelated-project-teacher', 'teacher')
        self.project = Project.objects.create(
            project_type=ProjectType.objects.get(code='INDEPENDENT'),
            title='Gizli Güvenlik Projesi',
            description='Yalnızca proje ilişkisi olan kullanıcılar görebilir.',
            created_by=self.owner,
            visibility='private',
            approval_status='pending',
        )

    def test_unrelated_teacher_cannot_open_or_list_private_project(self):
        self.client.force_login(self.teacher)
        detail = self.client.get(reverse('projects:project_detail', args=[self.project.pk]))
        self.assertRedirects(detail, reverse('projects:project_list'))
        self.assertNotContains(self.client.get(reverse('dashboard:projects')), self.project.title)

    def test_assigned_advisor_can_open_private_project(self):
        self.project.advisor = self.teacher
        self.project.save(update_fields=['advisor', 'updated_at'])
        self.client.force_login(self.teacher)
        self.assertEqual(
            self.client.get(reverse('projects:project_detail', args=[self.project.pk])).status_code,
            200,
        )
