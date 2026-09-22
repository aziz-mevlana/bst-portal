from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog, Notification

from .forms import RequestForm
from .models import Project, ProjectRequest, ProjectRequestApplication, ProjectType
from .services import accept_project_request_application


class GenericProjectRequestCapstoneBoundaryTests(TestCase):
    def setUp(self):
        self.teacher = self.create_user('request-boundary-teacher', 'teacher')
        self.student = self.create_user('request-boundary-student', 'student')
        self.normal_type = ProjectType.objects.get(code='RESEARCH')
        self.capstone_type = ProjectType.objects.get(code='CAPSTONE')
        self.client.force_login(self.teacher)

    def create_user(self, username, user_type):
        user = User.objects.create_user(username, password='StrongPassword123!')
        user.profile.user_type = user_type
        user.profile.class_level = '2' if user_type == 'student' else None
        user.profile.save(update_fields=['user_type', 'class_level'])
        return user

    def request_data(self, *, project_type=None, title='Generic proje ilanı'):
        return {
            'title': title,
            'project_type': (project_type or self.normal_type).pk,
            'course': '',
            'description': 'İlan açıklaması.',
            'requirements': '',
            'expected_output': 'Çalışan proje',
            'estimated_duration': '',
            'semester': '',
            'year': '',
            'deadline': '',
            'team_size': '',
            'status': 'open',
            'supervision_type': 'supervised',
        }

    def create_request(self, *, project_type=None, title='Mevcut proje ilanı'):
        return ProjectRequest.objects.create(
            title=title,
            project_type=project_type or self.normal_type,
            teacher=self.teacher,
            description='İlan açıklaması.',
            expected_output='Çalışan proje',
            status='open',
            supervision_type='supervised',
        )

    def test_new_request_form_does_not_offer_capstone(self):
        form = RequestForm()

        self.assertNotIn(self.capstone_type, form.fields['project_type'].queryset)
        self.assertIn(self.normal_type, form.fields['project_type'].queryset)

    def test_manipulated_capstone_request_create_is_rejected(self):
        response = self.client.post(
            reverse('projects:request_create'),
            self.request_data(project_type=self.capstone_type, title='Kaçak CAPSTONE ilanı'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'generic proje ilanı akışından oluşturulamaz')
        self.assertFalse(ProjectRequest.objects.filter(title='Kaçak CAPSTONE ilanı').exists())

    def test_normal_request_cannot_be_changed_to_capstone(self):
        project_request = self.create_request()

        response = self.client.post(
            reverse('projects:request_edit', args=[project_request.pk]),
            self.request_data(project_type=self.capstone_type, title='Dönüşüm denemesi'),
        )

        self.assertEqual(response.status_code, 200)
        project_request.refresh_from_db()
        self.assertEqual(project_request.project_type, self.normal_type)
        self.assertEqual(project_request.title, 'Mevcut proje ilanı')

    def test_legacy_capstone_request_cannot_be_changed_to_another_type(self):
        project_request = self.create_request(
            project_type=self.capstone_type,
            title='Legacy CAPSTONE ilanı',
        )

        response = self.client.post(
            reverse('projects:request_edit', args=[project_request.pk]),
            self.request_data(project_type=self.normal_type, title='Normal tipe dönüşüm'),
        )

        self.assertEqual(response.status_code, 200)
        project_request.refresh_from_db()
        self.assertEqual(project_request.project_type, self.capstone_type)
        self.assertEqual(project_request.title, 'Legacy CAPSTONE ilanı')

    def test_capstone_application_acceptance_has_no_side_effects(self):
        project_request = self.create_request(project_type=self.capstone_type)
        application = ProjectRequestApplication.objects.create(
            project_request=project_request,
            student=self.student,
            motivation='Başvurmak istiyorum.',
        )
        original_status = project_request.status

        with self.assertRaises(ValidationError):
            accept_project_request_application(
                application_id=application.pk,
                reviewer=self.teacher,
            )

        project_request.refresh_from_db()
        application.refresh_from_db()
        self.assertFalse(Project.objects.exists())
        self.assertEqual(application.status, 'pending')
        self.assertEqual(project_request.status, original_status)
        self.assertIsNone(project_request.created_project_id)
        self.assertFalse(Notification.objects.filter(
            notification_type__in=['application_accepted', 'application_rejected'],
        ).exists())
        self.assertFalse(AuditLog.objects.filter(
            action__in=['project_request.application_accepted', 'project.auto_created'],
        ).exists())

    def test_non_capstone_application_acceptance_still_creates_project(self):
        project_request = self.create_request()
        application = ProjectRequestApplication.objects.create(
            project_request=project_request,
            student=self.student,
            motivation='Normal ilana başvuru.',
        )

        project, created = accept_project_request_application(
            application_id=application.pk,
            reviewer=self.teacher,
        )

        application.refresh_from_db()
        project_request.refresh_from_db()
        self.assertTrue(created)
        self.assertEqual(project.project_type, self.normal_type)
        self.assertEqual(application.status, 'accepted')
        self.assertEqual(project_request.status, 'student_selected')
        self.assertEqual(project_request.created_project, project)
