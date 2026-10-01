from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Course, CourseInstructor, CourseProjectAssignment, CourseProjectWork,
    Project, ProjectType, ProjectUpdate,
)


class ProjectUpdateManagementTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('update-owner')
        self.advisor = User.objects.create_user('update-advisor')
        self.member = User.objects.create_user('update-member')
        self.outsider = User.objects.create_user('update-outsider')
        self.project_type = ProjectType.objects.get(code='INDEPENDENT')
        self.project = Project.objects.create(
            title='Güncelleme projesi', project_type=self.project_type,
            created_by=self.owner, advisor=self.advisor,
            visibility='public', approval_status='approved',
        )
        self.project.team.add(self.member)
        self.update = ProjectUpdate.objects.create(
            project=self.project, created_by=self.owner,
            version='v1', title='İlk sürüm', description='İlk açıklama',
        )
        self.edit_url = reverse('projects:edit_project_update', args=[self.project.pk, self.update.pk])
        self.delete_url = reverse('projects:delete_project_update', args=[self.project.pk, self.update.pk])
        self.detail_url = self.project.get_absolute_url()

    def test_authorized_edit_preserves_identity_timestamp_and_author_without_notification(self):
        created_at = self.update.created_at
        for user in (self.owner, self.advisor, self.member):
            with self.subTest(user=user.username), patch('projects.views.create_notification') as notify:
                self.client.force_login(user)
                self.assertContains(self.client.get(self.edit_url), 'Güncellemeyi düzenle')
                response = self.client.post(self.edit_url, {
                    'title': 'Yeni başlık', 'description': 'Yeni açıklama', 'version': 'v2',
                    'created_by': user.pk, 'created_at': '2000-01-01', 'project': 999999,
                })
                self.assertRedirects(response, self.detail_url + '#updates')
                self.update.refresh_from_db()
                self.assertEqual(self.update.title, 'Yeni başlık')
                self.assertEqual(self.update.description, 'Yeni açıklama')
                self.assertEqual(self.update.version, 'v2')
                self.assertEqual(self.update.created_at, created_at)
                self.assertEqual(self.update.created_by, self.owner)
                self.assertEqual(self.update.project_id, self.project.pk)
                self.assertEqual(ProjectUpdate.objects.count(), 1)
                notify.assert_not_called()

    def test_invalid_edit_does_not_change_existing_record(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.edit_url, {'title': 'Değişmesin', 'description': ''})
        self.assertEqual(response.status_code, 200)
        self.assertIn('description', response.context['form'].errors)
        self.update.refresh_from_db()
        self.assertEqual(self.update.title, 'İlk sürüm')

    def test_unauthorized_edit_get_and_post(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.edit_url).status_code, 404)
        self.assertEqual(self.client.post(self.edit_url, {'description': 'Forged'}).status_code, 404)
        self.update.refresh_from_db()
        self.assertEqual(self.update.description, 'İlk açıklama')

    def test_cross_project_edit_and_delete_are_rejected_even_for_owner_of_both(self):
        other = Project.objects.create(title='Diğer proje', project_type=self.project_type, created_by=self.owner)
        self.client.force_login(self.owner)
        edit_url = reverse('projects:edit_project_update', args=[other.pk, self.update.pk])
        delete_url = reverse('projects:delete_project_update', args=[other.pk, self.update.pk])
        self.assertEqual(self.client.get(edit_url).status_code, 404)
        self.assertEqual(self.client.post(edit_url, {'description': 'Forged'}).status_code, 404)
        self.assertEqual(self.client.post(delete_url, {'confirm_delete': 'yes'}).status_code, 404)
        self.update.refresh_from_db()
        self.assertEqual(self.update.project, self.project)

    def test_authorized_delete_removes_only_update_without_notification(self):
        for user in (self.owner, self.advisor, self.member):
            with self.subTest(user=user.username), patch('projects.views.create_notification') as notify:
                update = ProjectUpdate.objects.create(project=self.project, description='Silinecek')
                self.client.force_login(user)
                response = self.client.post(
                    reverse('projects:delete_project_update', args=[self.project.pk, update.pk]),
                    {'confirm_delete': 'yes'},
                )
                self.assertRedirects(response, self.detail_url + '#updates')
                self.assertFalse(ProjectUpdate.objects.filter(pk=update.pk).exists())
                self.assertTrue(ProjectUpdate.objects.filter(pk=self.update.pk).exists())
                self.assertTrue(Project.objects.filter(pk=self.project.pk).exists())
                self.assertTrue(User.objects.filter(pk=self.owner.pk).exists())
                notify.assert_not_called()

    def test_unauthorized_delete(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.post(self.delete_url, {'confirm_delete': 'yes'}).status_code, 404)
        self.assertTrue(ProjectUpdate.objects.filter(pk=self.update.pk).exists())

    def test_delete_is_post_only_requires_confirmation_and_csrf(self):
        self.client.force_login(self.owner)
        for method in ('get', 'head', 'put', 'delete'):
            with self.subTest(method=method):
                self.assertEqual(getattr(self.client, method)(self.delete_url).status_code, 405)
        self.assertRedirects(self.client.post(self.delete_url), self.detail_url + '#updates')
        self.assertTrue(ProjectUpdate.objects.filter(pk=self.update.pk).exists())
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(self.delete_url, {'confirm_delete': 'yes'}).status_code, 403)
        csrf_client.get(self.detail_url)
        response = csrf_client.post(self.delete_url, {
            'confirm_delete': 'yes', 'csrfmiddlewaretoken': csrf_client.cookies['csrftoken'].value,
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProjectUpdate.objects.filter(pk=self.update.pk).exists())

    def test_actions_visible_only_with_existing_update_permission(self):
        for user in (self.owner, self.advisor, self.member, self.outsider, None):
            with self.subTest(user=user):
                self.client.logout()
                if user:
                    self.client.force_login(user)
                response = self.client.get(self.detail_url)
                if user in (self.owner, self.advisor, self.member):
                    self.assertContains(response, self.edit_url)
                    self.assertContains(response, self.delete_url)
                    self.assertContains(response, 'Bu güncellemeyi kalıcı olarak silmeyi onaylıyorum.')
                    self.assertContains(response, 'İlk sürüm')
                else:
                    self.assertNotContains(response, self.edit_url)
                    self.assertNotContains(response, self.delete_url)

    def test_anonymous_mutations_require_login(self):
        self.assertEqual(self.client.post(self.edit_url, {'description': 'Forged'}).status_code, 302)
        self.assertEqual(self.client.post(self.delete_url, {'confirm_delete': 'yes'}).status_code, 302)
        self.assertTrue(ProjectUpdate.objects.filter(pk=self.update.pk).exists())

    def test_capstone_updates_are_excluded(self):
        self.project.project_type = ProjectType.objects.get(code='CAPSTONE')
        self.project.save()
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.edit_url).status_code, 404)
        self.assertEqual(self.client.post(self.edit_url, {'description': 'Forged'}).status_code, 404)
        self.assertEqual(self.client.post(self.delete_url, {'confirm_delete': 'yes'}).status_code, 404)
        response = self.client.get(self.detail_url)
        self.assertNotContains(response, self.edit_url)
        self.assertNotContains(response, self.delete_url)

    def test_course_work_updates_are_excluded_including_cancelled_assignments(self):
        self.advisor.profile.user_type = 'teacher'
        self.advisor.profile.save()
        course = Course.objects.get(code='BST 333')
        CourseInstructor.objects.create(course=course, instructor=self.advisor)
        now = timezone.now()
        assignment = CourseProjectAssignment.objects.create(
            course=course, instructor=self.advisor, topic='Akademik çalışma',
            join_deadline=now + timedelta(days=1), starts_at=now + timedelta(days=2), ends_at=now + timedelta(days=30),
        )
        self.project.course = course
        self.project.project_type = ProjectType.objects.get(code='COURSE')
        self.project.save()
        CourseProjectWork.objects.create(assignment=assignment, project=self.project, owner=self.owner)
        self.client.force_login(self.owner)
        for active in (True, False):
            assignment.is_active = active
            assignment.save()
            with self.subTest(active=active):
                self.assertEqual(self.client.get(self.edit_url).status_code, 404)
                self.assertEqual(self.client.post(self.edit_url, {'description': 'Forged'}).status_code, 404)
                self.assertEqual(self.client.post(self.delete_url, {'confirm_delete': 'yes'}).status_code, 404)
        self.update.refresh_from_db()
        self.assertEqual(self.update.description, 'İlk açıklama')

    def test_generic_portfolio_course_project_updates_remain_editable(self):
        self.project.project_type = ProjectType.objects.get(code='COURSE')
        self.project.course = Course.objects.get(code='BST 333')
        self.project.save()
        self.client.force_login(self.owner)
        response = self.client.post(self.edit_url, {'title': 'Portföy güncellemesi', 'description': 'Yeni gelişme'})
        self.assertRedirects(response, self.detail_url + '#updates')
        self.update.refresh_from_db()
        self.assertEqual(self.update.title, 'Portföy güncellemesi')
        self.assertRedirects(self.client.post(self.delete_url, {'confirm_delete': 'yes'}), self.detail_url + '#updates')

    def test_existing_creation_still_creates_single_update_and_notifies_saved_project_user(self):
        self.project.saves.create(user=self.outsider)
        self.client.force_login(self.owner)
        with patch('projects.views.create_notification') as notify:
            response = self.client.post(reverse('projects:add_project_update', args=[self.project.pk]), {
                'title': 'Yeni güncelleme', 'description': 'Yeni gelişme',
            })
            self.assertRedirects(response, reverse('projects:project_detail', args=[self.project.pk]))
            notify.assert_called_once()
        self.assertEqual(self.project.updates.count(), 2)
