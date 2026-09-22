from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .forms import ProjectForm
from .models import Project, ProjectFeedback, ProjectType


class GenericProjectCapstoneBoundaryTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('generic-project-owner', password='StrongPassword123!')
        self.normal_type = ProjectType.objects.get(code='INDEPENDENT')
        self.capstone_type = ProjectType.objects.get(code='CAPSTONE')
        self.client.force_login(self.owner)

    def project_data(self, *, project_type=None, title='Generic proje'):
        return {
            'project_type': (project_type or self.normal_type).pk,
            'creation_source': 'STUDENT_IDEA',
            'title': title,
            'description': 'Generic proje açıklaması.',
            'expected_output': '',
            'project_link': '',
            'advisor': '',
            'team_entity': '',
            'development_status': 'idea',
            'visibility': 'private',
            'repository_path': '',
        }

    def test_create_form_does_not_offer_capstone_project_type(self):
        form = ProjectForm(current_user=self.owner)

        self.assertNotIn(self.capstone_type, form.fields['project_type'].queryset)
        self.assertIn(self.normal_type, form.fields['project_type'].queryset)

    def test_manipulated_capstone_create_is_rejected(self):
        response = self.client.post(
            reverse('projects:project_create'),
            self.project_data(project_type=self.capstone_type, title='Kaçak CAPSTONE'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'yalnızca özel CAPSTONE oluşturma akışıyla')
        self.assertFalse(Project.objects.filter(title='Kaçak CAPSTONE').exists())

    def test_generic_create_still_accepts_normal_project_type(self):
        response = self.client.post(
            reverse('projects:project_create'),
            self.project_data(title='Normal oluşturulan proje'),
        )

        project = Project.objects.get(title='Normal oluşturulan proje')
        self.assertRedirects(response, reverse('projects:project_detail', args=[project.pk]))
        self.assertEqual(project.project_type, self.normal_type)

    def test_normal_project_cannot_be_converted_to_capstone(self):
        project = Project.objects.create(
            project_type=self.normal_type,
            title='Normal proje',
            created_by=self.owner,
        )

        response = self.client.post(
            reverse('projects:project_update', args=[project.pk]),
            self.project_data(project_type=self.capstone_type, title='Dönüştürme denemesi'),
        )

        self.assertEqual(response.status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.project_type, self.normal_type)
        self.assertEqual(project.title, 'Normal proje')

    def test_capstone_project_cannot_be_converted_to_normal_type(self):
        project = Project.objects.create(
            project_type=self.capstone_type,
            title='Mevcut CAPSTONE',
            created_by=self.owner,
        )

        response = self.client.post(
            reverse('projects:project_update', args=[project.pk]),
            self.project_data(project_type=self.normal_type, title='Normalleştirme denemesi'),
        )

        self.assertEqual(response.status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.project_type, self.capstone_type)
        self.assertEqual(project.title, 'Mevcut CAPSTONE')

    def test_capstone_project_can_update_allowed_field_without_changing_type(self):
        project = Project.objects.create(
            project_type=self.capstone_type,
            title='Eski CAPSTONE başlığı',
            created_by=self.owner,
        )

        response = self.client.post(
            reverse('projects:project_update', args=[project.pk]),
            self.project_data(project_type=self.capstone_type, title='Yeni CAPSTONE başlığı'),
        )

        self.assertRedirects(response, reverse('projects:project_detail', args=[project.pk]))
        project.refresh_from_db()
        self.assertEqual(project.title, 'Yeni CAPSTONE başlığı')
        self.assertEqual(project.project_type, self.capstone_type)

    def test_capstone_update_preserves_academic_critical_fields(self):
        advisor = User.objects.create_user('capstone-guard-advisor')
        advisor.profile.user_type = 'teacher'
        advisor.profile.save(update_fields=['user_type', 'class_level'])
        replacement_advisor = User.objects.create_user('capstone-guard-replacement')
        replacement_advisor.profile.user_type = 'teacher'
        replacement_advisor.profile.save(update_fields=['user_type', 'class_level'])
        team_member = User.objects.create_user('capstone-guard-team')
        project = Project.objects.create(
            project_type=self.capstone_type,
            title='Korunan CAPSTONE',
            created_by=self.owner,
            advisor=advisor,
            status='in_review',
            approval_status='pending',
            development_status='idea',
            visibility='private',
            is_private=True,
        )
        project.team.add(self.owner)
        data = self.project_data(project_type=self.capstone_type, title='Güvenli metadata')
        data.update({
            'advisor': replacement_advisor.pk,
            'team': [team_member.pk],
            'development_status': 'completed',
            'visibility': 'public',
            'creation_source': 'EXTERNAL_CALL',
        })

        response = self.client.post(
            reverse('projects:project_update', args=[project.pk]),
            data,
        )

        self.assertRedirects(response, reverse('projects:project_detail', args=[project.pk]))
        project.refresh_from_db()
        self.assertEqual(project.title, 'Güvenli metadata')
        self.assertEqual(project.advisor, advisor)
        self.assertEqual(set(project.team.values_list('pk', flat=True)), {self.owner.pk})
        self.assertEqual(project.status, 'in_review')
        self.assertEqual(project.approval_status, 'pending')
        self.assertEqual(project.development_status, 'idea')
        self.assertEqual(project.visibility, 'private')
        self.assertTrue(project.is_private)
        self.assertEqual(project.creation_source, 'STUDENT_IDEA')

    def test_capstone_form_omits_generic_academic_workflow_fields(self):
        project = Project.objects.create(
            project_type=self.capstone_type,
            title='Form guard CAPSTONE',
            created_by=self.owner,
        )

        form = ProjectForm(instance=project, current_user=self.owner)

        self.assertTrue(form.fields['project_type'].disabled)
        for field in (
            'creation_source', 'advisor', 'team_entity', 'team',
            'development_status', 'visibility',
        ):
            self.assertNotIn(field, form.fields)

    def test_generic_workflow_actions_cannot_mutate_or_delete_capstone(self):
        advisor = User.objects.create_user('capstone-action-advisor')
        advisor.profile.user_type = 'teacher'
        advisor.profile.save(update_fields=['user_type', 'class_level'])
        project = Project.objects.create(
            project_type=self.capstone_type,
            title='Action guard CAPSTONE',
            created_by=self.owner,
            advisor=advisor,
            status='in_review',
            approval_status='pending',
            development_status='idea',
        )

        self.client.force_login(advisor)
        self.client.post(reverse('projects:approve_project', args=[project.pk]))
        project.refresh_from_db()
        self.assertEqual((project.status, project.approval_status), ('in_review', 'pending'))
        self.client.post(
            reverse('projects:send_feedback', args=[project.pk]),
            {'content': 'Generic approval feedback bypass denemesi.'},
        )
        self.assertFalse(ProjectFeedback.objects.filter(project=project).exists())

        self.client.force_login(self.owner)
        Project.objects.filter(pk=project.pk).update(
            status='approved', approval_status='approved', development_status='idea'
        )
        self.client.post(reverse('projects:start_project', args=[project.pk]))
        project.refresh_from_db()
        self.assertEqual((project.status, project.development_status), ('approved', 'idea'))

        Project.objects.filter(pk=project.pk).update(
            status='in_progress', development_status='in_progress'
        )
        self.client.post(reverse('projects:complete_project', args=[project.pk]))
        project.refresh_from_db()
        self.assertEqual(
            (project.status, project.development_status),
            ('in_progress', 'in_progress'),
        )

        self.client.force_login(advisor)
        response = self.client.post(
            reverse('projects:change_project_status', args=[project.pk]),
            data='{"status":"completed"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 409)
        project.refresh_from_db()
        self.assertEqual(project.status, 'in_progress')

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('projects:project_delete', args=[project.pk]),
            {'confirm_delete': 'yes'},
        )
        self.assertRedirects(response, reverse('projects:project_detail', args=[project.pk]))
        self.assertTrue(Project.objects.filter(pk=project.pk).exists())

    def test_capstone_generic_detail_hides_workflow_and_delete_actions(self):
        project = Project.objects.create(
            project_type=self.capstone_type,
            title='CAPSTONE generic detail',
            created_by=self.owner,
            approval_status='approved',
            development_status='idea',
        )

        response = self.client.get(reverse('projects:project_detail', args=[project.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('projects:project_update', args=[project.pk]))
        self.assertNotContains(response, reverse('projects:start_project', args=[project.pk]))
        self.assertNotContains(response, reverse('projects:complete_project', args=[project.pk]))
        self.assertNotContains(response, reverse('projects:project_delete', args=[project.pk]))

    def test_capstone_boundary_validation_errors_do_not_return_500(self):
        normal_project = Project.objects.create(
            project_type=self.normal_type,
            title='Sınır testi',
            created_by=self.owner,
        )

        create_response = self.client.post(
            reverse('projects:project_create'),
            self.project_data(project_type=self.capstone_type, title='Geçersiz create'),
        )
        update_response = self.client.post(
            reverse('projects:project_update', args=[normal_project.pk]),
            self.project_data(project_type=self.capstone_type, title='Geçersiz update'),
        )

        self.assertEqual(create_response.status_code, 200)
        self.assertEqual(update_response.status_code, 200)
        self.assertContains(update_response, 'normal düzenleme akışında CAPSTONE olarak değiştirilemez')
