import base64
import tempfile

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.models import AuditLog, Notification

from .forms import (
    ProjectImageUploadForm, ProjectMediaForm, ProjectRepositoryForm, TeamForm,
    TeamInviteForm, TeamOpenRoleForm,
)
from .models import (
    Project, ProjectFeature, ProjectLike, ProjectMedia, ProjectRepository, ProjectType, Team, TeamInvitation,
    TeamMembership, TeamRole, validate_project_image,
)
from .team_services import create_team, invite_user, respond_to_invitation


def user_with_role(username, role='student'):
    user = User.objects.create_user(username, f'{username}@example.com', 'StrongPassword123!')
    user.profile.user_type = role
    user.profile.class_level = '2' if role in {'student', 'staff_student'} else None
    user.profile.save()
    return user


class RemovedGitHubIntegrationTests(SimpleTestCase):
    def test_celery_schedule_does_not_reference_removed_github_tasks(self):
        scheduled_tasks = {
            item.get('task', '') for item in settings.CELERY_BEAT_SCHEDULE.values()
        }
        self.assertFalse(any(task.startswith('projects.tasks.') for task in scheduled_tasks))


class TeamWorkflowTests(TestCase):
    def setUp(self):
        self.leader = user_with_role('team-leader')
        self.invitee = user_with_role('team-invitee')
        form = TeamForm(data={
            'name': 'BST Vision', 'description': 'Görüntü işleme ekibi',
            'recruitment_open': 'on',
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.team = create_team(leader=self.leader, form=form)

    def test_creator_is_added_as_leader_membership_atomically(self):
        membership = TeamMembership.objects.get(team=self.team, user=self.leader)
        self.assertEqual(membership.role, TeamRole.TEAM_LEAD)

    def test_recent_team_forms_use_turkish_labels_and_placeholders(self):
        form = TeamForm()
        self.assertEqual(form.fields['name'].label, 'Ekip Adı')
        self.assertEqual(form.fields['description'].label, 'Açıklama')
        self.assertEqual(form.fields['technologies'].label, 'Teknolojiler')
        self.assertEqual(form.fields['work_areas'].label, 'Çalışma Alanları')
        self.assertEqual(form.fields['recruitment_open'].label, 'Üye Alımı Açık')
        self.assertEqual(form.fields['leader_role'].label, 'Ekipteki Rolünüz')
        self.assertIn((TeamRole.BACKEND, 'Backend Geliştirici'), form.fields['leader_role'].choices)
        role_form = TeamOpenRoleForm()
        self.assertEqual(role_form.fields['required_technologies'].label, 'Gerekli Teknolojiler')
        self.assertIn((TeamRole.AI_ML, 'Yapay Zekâ / Makine Öğrenmesi'), role_form.fields['title'].choices)

    def test_invitation_creates_no_membership_before_acceptance_and_accept_is_idempotent(self):
        invitation = invite_user(
            team=self.team, inviter=self.leader, invited_user=self.invitee,
            proposed_role=TeamRole.BACKEND,
        )
        self.assertFalse(TeamMembership.objects.filter(team=self.team, user=self.invitee).exists())
        first = respond_to_invitation(invitation_id=invitation.pk, user=self.invitee, accept=True)
        second = respond_to_invitation(invitation_id=invitation.pk, user=self.invitee, accept=True)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.role, TeamRole.BACKEND)
        self.assertEqual(TeamMembership.objects.filter(team=self.team, user=self.invitee).count(), 1)

    def test_only_leader_can_invite_and_duplicate_pending_invite_is_rejected(self):
        outsider = user_with_role('team-outsider')
        with self.assertRaises(PermissionDenied):
            invite_user(team=self.team, inviter=outsider, invited_user=self.invitee)
        invite_user(team=self.team, inviter=self.leader, invited_user=self.invitee)
        with self.assertRaises(ValidationError):
            invite_user(team=self.team, inviter=self.leader, invited_user=self.invitee)
        self.assertEqual(TeamInvitation.objects.filter(team=self.team, invited_user=self.invitee).count(), 1)

    def test_role_fields_reject_arbitrary_values(self):
        invite_form = TeamInviteForm(
            data={'invited_user': self.invitee.pk, 'proposed_role': 'site-admin'},
            team=self.team,
        )
        self.assertFalse(invite_form.is_valid())
        with self.assertRaises(ValidationError):
            invite_user(
                team=self.team,
                inviter=self.leader,
                invited_user=self.invitee,
                proposed_role='site-admin',
            )

    def test_only_real_team_leader_can_update_member_role(self):
        membership = TeamMembership.objects.create(
            team=self.team,
            user=self.invitee,
            role=TeamRole.GENERAL,
        )
        url = reverse('projects:team_membership_role_update', args=[self.team.slug, membership.pk])

        self.client.force_login(self.leader)
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url, {'role': TeamRole.BACKEND})
        self.assertRedirects(response, self.team.get_absolute_url())
        membership.refresh_from_db()
        self.assertEqual(membership.role, TeamRole.BACKEND)
        self.assertTrue(AuditLog.objects.filter(action='team.member_role_updated').exists())

        self.client.force_login(self.invitee)
        self.assertEqual(self.client.post(url, {'role': TeamRole.TEAM_LEAD}).status_code, 403)
        membership.refresh_from_db()
        self.assertEqual(membership.role, TeamRole.BACKEND)

    def test_team_lead_role_label_does_not_grant_management_permission(self):
        TeamMembership.objects.create(team=self.team, user=self.invitee, role=TeamRole.TEAM_LEAD)
        another_user = user_with_role('another-team-invitee')
        self.client.force_login(self.invitee)
        response = self.client.post(
            reverse('projects:team_invite', args=[self.team.slug]),
            {'invited_user': another_user.pk, 'proposed_role': TeamRole.FRONTEND},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(TeamInvitation.objects.filter(invited_user=another_user).exists())

    def test_team_entity_membership_does_not_grant_project_edit_permission(self):
        TeamMembership.objects.create(team=self.team, user=self.invitee, role='Üye')
        project = Project.objects.create(
            project_type=ProjectType.objects.get(code='INDEPENDENT'),
            title='Kurumsal ekip projesi', created_by=self.leader, team_entity=self.team,
            visibility='public', approval_status='approved',
        )
        self.client.force_login(self.invitee)
        response = self.client.get(reverse('projects:project_update', args=[project.pk]))
        self.assertRedirects(response, reverse('projects:project_detail', args=[project.pk]))

    def test_leader_can_disband_team_and_linked_project_is_preserved(self):
        TeamMembership.objects.create(team=self.team, user=self.invitee, role='Üye')
        project = Project.objects.create(
            project_type=ProjectType.objects.get(code='INDEPENDENT'),
            title='Korunacak ekip projesi', created_by=self.leader, team_entity=self.team,
            visibility='public', approval_status='approved',
        )
        self.client.force_login(self.leader)
        url = reverse('projects:team_disband', args=[self.team.slug])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url, {'team_name': 'Yanlış ad'})
        self.assertTrue(Team.objects.filter(pk=self.team.pk).exists())
        response = self.client.post(url, {'team_name': self.team.name})
        self.assertRedirects(response, reverse('projects:team_list'))
        self.assertFalse(Team.objects.filter(pk=self.team.pk).exists())
        project.refresh_from_db()
        self.assertIsNone(project.team_entity_id)
        self.assertTrue(AuditLog.objects.filter(action='team.disbanded').exists())
        self.assertTrue(Notification.objects.filter(recipient=self.invitee, notification_type='system').exists())

    def test_admin_can_disband_another_team_but_outsider_cannot(self):
        outsider = user_with_role('team-disband-outsider')
        url = reverse('projects:team_disband', args=[self.team.slug])
        self.client.force_login(outsider)
        self.assertEqual(self.client.post(url, {'team_name': self.team.name}).status_code, 403)
        admin = User.objects.create_user('team-admin', 'team-admin@example.com', 'StrongPassword123!', is_staff=True)
        self.client.force_login(admin)
        self.client.post(url, {'team_name': self.team.name})
        self.assertFalse(Team.objects.filter(pk=self.team.pk).exists())


class ProjectLikeAndFeatureTests(TestCase):
    def setUp(self):
        self.owner = user_with_role('like-owner')
        self.viewer = user_with_role('like-viewer')
        self.project = Project.objects.create(
            project_type=ProjectType.objects.get(code='INDEPENDENT'),
            title='Beğenilen proje', created_by=self.owner,
            visibility='public', approval_status='approved', development_status='completed',
        )

    def test_like_endpoint_is_post_only_and_toggles_unique_record(self):
        self.client.force_login(self.viewer)
        url = reverse('projects:toggle_project_like', args=[self.project.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        self.assertEqual(ProjectLike.objects.filter(project=self.project, user=self.viewer).count(), 1)
        self.client.post(url)
        self.assertFalse(ProjectLike.objects.filter(project=self.project, user=self.viewer).exists())

    def test_tenth_like_notifies_owner_once_even_when_owner_is_tenth_liker(self):
        for index in range(9):
            liker = user_with_role(f'liker-{index}')
            ProjectLike.objects.create(project=self.project, user=liker)
        self.client.force_login(self.owner)
        self.client.post(reverse('projects:toggle_project_like', args=[self.project.pk]))
        self.assertEqual(
            Notification.objects.filter(
                recipient=self.owner, dedupe_key=f'project-like:{self.project.pk}:10'
            ).count(),
            1,
        )

    def test_bst_authority_cannot_feature_but_teacher_can(self):
        authority = user_with_role('feature-authority', 'staff_student')
        teacher = user_with_role('feature-teacher', 'teacher')
        url = reverse('projects:project_feature_toggle', args=[self.project.pk])
        self.client.force_login(authority)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(teacher)
        self.assertRedirects(self.client.post(url, {'description': 'Başarılı çalışma'}), self.project.get_absolute_url())
        feature = ProjectFeature.objects.get(project=self.project, is_active=True)
        self.assertEqual(feature.selected_by, teacher)
        self.assertEqual(feature.description, 'Başarılı çalışma')


class ProjectImageRulesTests(TestCase):
    PNG_1X1 = base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
    )

    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(self.media_dir.cleanup)
        owner = user_with_role('image-owner')
        self.project = Project.objects.create(
            project_type=ProjectType.objects.get(code='INDEPENDENT'),
            title='Görselli proje', created_by=owner,
        )

    def image(self, name):
        return SimpleUploadedFile(name, self.PNG_1X1, content_type='image/png')

    def pdf(self, name='document.pdf', content_type='application/pdf'):
        return SimpleUploadedFile(
            name, b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n',
            content_type=content_type,
        )

    def test_image_limit_is_five_megabytes(self):
        oversized = SimpleUploadedFile(
            'large.png', b'x' * (5 * 1024 * 1024 + 1), content_type='image/png'
        )
        with self.assertRaisesRegex(ValidationError, '5 MB'):
            validate_project_image(oversized)

    def test_cover_index_must_reference_an_uploaded_image(self):
        form = ProjectImageUploadForm(
            data={'cover_index': '4'}, files={'images': self.image('only.png')}
        )
        self.assertFalse(form.is_valid())
        self.assertIn('cover_index', form.errors)

    def test_saving_new_cover_unsets_previous_cover(self):
        first = ProjectMedia.objects.create(
            project=self.project, media_type='image', file=self.image('first.png'), is_cover=True,
        )
        second = ProjectMedia.objects.create(
            project=self.project, media_type='image', file=self.image('second.png'), is_cover=True,
        )
        first.refresh_from_db()
        self.assertFalse(first.is_cover)
        self.assertTrue(second.is_cover)

    def test_named_assets_are_limited_to_one_per_project(self):
        ProjectMedia.objects.create(
            project=self.project, media_type='project_logo', file=self.image('first-logo.png'),
        )
        with self.assertRaises(ValidationError):
            ProjectMedia.objects.create(
                project=self.project, media_type='project_logo', file=self.image('second-logo.png'),
            )

    def test_pdf_form_checks_extension_content_mime_and_trailer(self):
        self.assertTrue(ProjectImageUploadForm(files={'pitch_deck': self.pdf()}).is_valid())

        wrong_extension = ProjectImageUploadForm(files={'pitch_deck': self.pdf('document.txt')})
        self.assertFalse(wrong_extension.is_valid())

        fake_pdf = SimpleUploadedFile('fake.pdf', b'not a pdf', content_type='application/pdf')
        invalid_content = ProjectImageUploadForm(files={'pitch_deck': fake_pdf})
        self.assertFalse(invalid_content.is_valid())

        wrong_mime = ProjectImageUploadForm(
            files={'pitch_deck': self.pdf(content_type='text/plain')}
        )
        self.assertFalse(wrong_mime.is_valid())

        incomplete = SimpleUploadedFile(
            'incomplete.pdf', b'%PDF-1.4\n1 0 obj\n', content_type='application/pdf'
        )
        invalid_trailer = ProjectImageUploadForm(files={'documentation': incomplete})
        self.assertFalse(invalid_trailer.is_valid())

    def test_generic_showcase_form_does_not_offer_named_asset_slots(self):
        choices = {value for value, _label in ProjectMediaForm().fields['media_type'].choices}
        self.assertTrue({'image', 'video', 'demo', 'document'}.issubset(choices))
        self.assertFalse({'cover_image', 'project_logo', 'pitch_deck', 'documentation'} & choices)


class ProjectFormIntegrationTests(TestCase):
    PNG_1X1 = ProjectImageRulesTests.PNG_1X1

    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(self.media_dir.cleanup)
        self.owner = user_with_role('project-form-owner')
        self.project_type = ProjectType.objects.get(code='INDEPENDENT')
        self.client.force_login(self.owner)

    def image(self, name):
        return SimpleUploadedFile(name, self.PNG_1X1, content_type='image/png')

    def pdf(self, name):
        return SimpleUploadedFile(
            name, b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n',
            content_type='application/pdf',
        )

    def project_data(self, **overrides):
        data = {
            'project_type': self.project_type.pk,
            'creation_source': 'STUDENT_IDEA',
            'title': 'Entegre proje formu',
            'description': 'Form entegrasyonunu doğrulayan proje.',
            'expected_output': 'Çalışan uygulama',
            'project_link': 'https://demo.example.com',
            'development_status': 'idea',
            'visibility': 'private',
            'repository_path': 'bst/proje',
        }
        data.update(overrides)
        return data

    def test_create_form_saves_general_link_repository_and_multiple_images_atomically(self):
        data = self.project_data(images=[self.image('one.png'), self.image('two.png')], cover_index='1')
        response = self.client.post(reverse('projects:project_create'), data)

        project = Project.objects.get(title='Entegre proje formu')
        self.assertRedirects(response, reverse('projects:project_detail', args=[project.pk]))
        self.assertEqual(project.project_link, 'https://demo.example.com')
        self.assertEqual(project.repository.repository_path, 'bst/proje')
        self.assertEqual(project.media.filter(media_type='image').count(), 2)
        self.assertEqual(project.media.get(is_cover=True).order, 1)
        self.assertTrue(AuditLog.objects.filter(action='project.created', target_id=str(project.pk)).exists())

    def test_create_form_saves_cover_logo_gallery_and_pdf_assets(self):
        data = self.project_data(
            cover_image=self.image('cover.png'),
            project_logo=self.image('logo.png'),
            images=[self.image('screen.png'), self.image('architecture.png')],
            pitch_deck=self.pdf('pitch.pdf'),
            pitch_deck_is_public='on',
            documentation=self.pdf('documentation.pdf'),
        )
        response = self.client.post(reverse('projects:project_create'), data)

        project = Project.objects.get(title='Entegre proje formu')
        self.assertRedirects(response, reverse('projects:project_detail', args=[project.pk]))
        self.assertEqual(project.media.filter(media_type='image').count(), 2)
        self.assertEqual(project.media.filter(media_type='cover_image', is_cover=True).count(), 1)
        self.assertEqual(project.media.filter(media_type='project_logo').count(), 1)
        self.assertEqual(project.media.filter(media_type='documentation').count(), 1)
        self.assertTrue(project.media.get(media_type='pitch_deck').is_public)

    def test_update_form_changes_repository_adds_image_and_keeps_existing_cover(self):
        project = Project.objects.create(
            project_type=self.project_type, title='Eski başlık', created_by=self.owner,
            visibility='private', development_status='idea',
        )
        ProjectRepository.objects.create(project=project, repository_path='bst/eski')
        existing = ProjectMedia.objects.create(
            project=project, media_type='image', file=self.image('cover.png'), is_cover=True,
        )
        data = self.project_data(
            title='Güncellenen proje', repository_path='bst/yeni',
            project_link='https://project.example.com', images=[self.image('added.png')],
        )
        response = self.client.post(reverse('projects:project_update', args=[project.pk]), data)

        self.assertRedirects(response, reverse('projects:project_detail', args=[project.pk]))
        project.refresh_from_db()
        existing.refresh_from_db()
        self.assertEqual(project.title, 'Güncellenen proje')
        self.assertEqual(project.project_link, 'https://project.example.com')
        self.assertEqual(project.repository.repository_path, 'bst/yeni')
        self.assertEqual(project.media.filter(media_type='image').count(), 2)
        self.assertTrue(existing.is_cover)
        self.assertTrue(AuditLog.objects.filter(action='project.updated', target_id=str(project.pk)).exists())

    def test_update_form_can_remove_general_link_and_repository(self):
        project = Project.objects.create(
            project_type=self.project_type, title='Bağlantılı proje', created_by=self.owner,
            project_link='https://project.example.com', visibility='private',
        )
        ProjectRepository.objects.create(project=project, repository_path='bst/kaldirilacak')

        response = self.client.post(
            reverse('projects:project_update', args=[project.pk]),
            self.project_data(title='Bağlantısız proje', project_link='', repository_path=''),
        )

        self.assertRedirects(response, reverse('projects:project_detail', args=[project.pk]))
        project.refresh_from_db()
        self.assertFalse(project.project_link)
        self.assertFalse(ProjectRepository.objects.filter(project=project).exists())

    def test_update_replaces_named_files_and_can_make_pitch_private(self):
        project = Project.objects.create(
            project_type=self.project_type, title='Dosyalı proje', created_by=self.owner,
            visibility='private', development_status='idea',
        )
        old_cover = ProjectMedia.objects.create(
            project=project, media_type='cover_image', file=self.image('old-cover.png'),
        )
        old_pitch = ProjectMedia.objects.create(
            project=project, media_type='pitch_deck', file=self.pdf('old-pitch.pdf'), is_public=True,
        )
        response = self.client.post(
            reverse('projects:project_update', args=[project.pk]),
            self.project_data(
                title='Dosyaları güncel proje', cover_image=self.image('new-cover.png'),
                pitch_deck=self.pdf('new-pitch.pdf'),
            ),
        )

        self.assertRedirects(response, reverse('projects:project_detail', args=[project.pk]))
        self.assertFalse(ProjectMedia.objects.filter(pk=old_cover.pk).exists())
        self.assertFalse(ProjectMedia.objects.filter(pk=old_pitch.pk).exists())
        self.assertEqual(project.media.filter(media_type='cover_image').count(), 1)
        self.assertEqual(project.media.filter(media_type='pitch_deck').count(), 1)
        self.assertFalse(project.media.get(media_type='pitch_deck').is_public)

    def test_deleting_cover_from_edit_page_promotes_next_image_and_returns_to_edit(self):
        project = Project.objects.create(
            project_type=self.project_type, title='Kapak projesi', created_by=self.owner,
        )
        cover = ProjectMedia.objects.create(
            project=project, media_type='image', file=self.image('cover.png'), is_cover=True,
        )
        next_image = ProjectMedia.objects.create(
            project=project, media_type='image', file=self.image('next.png'), order=1,
        )
        response = self.client.post(
            reverse('projects:project_media_delete', args=[cover.pk]),
            {'return_to': 'project_edit'},
        )

        self.assertRedirects(response, reverse('projects:project_update', args=[project.pk]))
        next_image.refresh_from_db()
        self.assertTrue(next_image.is_cover)

    def test_repository_field_is_optional_but_rejects_full_url(self):
        self.assertTrue(ProjectRepositoryForm(data={'repository_path': ''}).is_valid())
        form = ProjectRepositoryForm(data={'repository_path': 'https://github.com/bst/proje'})
        self.assertFalse(form.is_valid())
        self.assertIn('repository_path', form.errors)


class ProjectDocumentAccessTests(TestCase):
    PDF = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n'

    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(self.media_dir.cleanup)
        self.owner = user_with_role('document-owner')
        self.outsider = user_with_role('document-outsider')
        self.project = Project.objects.create(
            project_type=ProjectType.objects.get(code='INDEPENDENT'),
            title='Dosya erişim projesi', created_by=self.owner,
            visibility='public', approval_status='approved',
        )
        self.documentation = ProjectMedia.objects.create(
            project=self.project, media_type='documentation', file=self.pdf('documentation.pdf'),
        )
        self.pitch = ProjectMedia.objects.create(
            project=self.project, media_type='pitch_deck', file=self.pdf('pitch.pdf'), is_public=False,
        )

    def pdf(self, name):
        return SimpleUploadedFile(name, self.PDF, content_type='application/pdf')

    def media_url(self, media, disposition='view'):
        return reverse('projects:project_media_file', args=[media.pk, disposition])

    def test_public_detail_lists_documentation_but_hides_private_pitch(self):
        response = self.client.get(reverse('projects:project_detail', args=[self.project.pk]))
        self.assertContains(response, 'Proje Dokümantasyonu')
        self.assertContains(response, self.media_url(self.documentation, 'view'))
        self.assertNotContains(response, 'Yatırımcı Sunumu')
        self.assertNotContains(response, self.pitch.file.url)

    def test_documentation_supports_inline_view_and_attachment_download(self):
        view_response = self.client.get(self.media_url(self.documentation, 'view'))
        self.assertEqual(view_response.status_code, 200)
        self.assertEqual(view_response['Content-Type'], 'application/pdf')
        self.assertIn('inline', view_response['Content-Disposition'])
        view_response.close()

        download_response = self.client.get(self.media_url(self.documentation, 'download'))
        self.assertEqual(download_response.status_code, 200)
        self.assertIn('attachment', download_response['Content-Disposition'])
        download_response.close()

    def test_private_pitch_requires_project_management_permission(self):
        self.assertEqual(self.client.get(self.media_url(self.pitch)).status_code, 403)
        self.assertEqual(self.client.get(self.pitch.file.url).status_code, 403)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.media_url(self.pitch)).status_code, 403)
        self.assertEqual(self.client.get(self.pitch.file.url).status_code, 403)
        self.client.force_login(self.owner)
        response = self.client.get(self.media_url(self.pitch))
        self.assertEqual(response.status_code, 200)
        response.close()
        direct_response = self.client.get(self.pitch.file.url)
        self.assertEqual(direct_response.status_code, 200)
        direct_response.close()
        detail = self.client.get(reverse('projects:project_detail', args=[self.project.pk]))
        self.assertContains(detail, 'Yatırımcı Sunumu')

    def test_private_project_documents_are_not_available_to_outsiders(self):
        self.project.visibility = 'private'
        self.project.is_private = True
        self.project.save(update_fields=['visibility', 'is_private'])
        self.assertEqual(self.client.get(self.media_url(self.documentation)).status_code, 403)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.media_url(self.documentation)).status_code, 403)

    def test_invalid_disposition_and_unrelated_media_type_return_not_found(self):
        self.assertEqual(self.client.get(self.media_url(self.documentation, 'preview')).status_code, 404)
        image = ProjectMedia.objects.create(
            project=self.project, media_type='image',
            file=SimpleUploadedFile(
                'image.png', ProjectImageRulesTests.PNG_1X1, content_type='image/png'
            ),
        )
        self.assertEqual(self.client.get(self.media_url(image)).status_code, 404)
