from datetime import datetime, timedelta, timezone as datetime_timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from projects.models import Project, ProjectType

from .models import (
    CapstoneCheckpoint,
    CapstoneProject,
    CapstoneSubmissionAttempt,
    CapstoneSubmissionFile,
    CapstoneTask,
    CapstoneTerm,
)
from .storage import PrivateFileSystemStorage


class CapstoneSubmissionFileDeliveryTests(TestCase):
    FILE_CONTENT = b'private-capstone-submission-content'

    def setUp(self):
        self.private_directory = TemporaryDirectory()
        self.file_field = CapstoneSubmissionFile._meta.get_field('file')
        self.original_storage = self.file_field.storage
        self.file_field.storage = PrivateFileSystemStorage(location=self.private_directory.name)

        self.owner = self.create_user('delivery-owner', 'student')
        self.advisor = self.create_user('delivery-advisor', 'teacher')
        self.team_member = self.create_user('delivery-team', 'student')
        self.unrelated_student = self.create_user('delivery-student', 'student')
        self.unrelated_teacher = self.create_user('delivery-teacher', 'teacher')
        self.staff = self.create_user('delivery-staff', 'student', is_staff=True)
        self.superuser = self.create_user('delivery-superuser', 'student', is_superuser=True)

        starts_at = datetime(2026, 9, 1, 9, 0, tzinfo=datetime_timezone.utc)
        due_at = starts_at + timedelta(weeks=4)
        term = CapstoneTerm.objects.create(
            academic_year='2026-2027',
            semester=CapstoneTerm.Semester.FALL,
            starts_at=starts_at,
            midterm_at=starts_at + timedelta(weeks=8),
            final_at=starts_at + timedelta(weeks=16),
            is_active=True,
        )
        project = Project.objects.create(
            project_type=ProjectType.objects.get(code='CAPSTONE'),
            title='Private file delivery projesi',
            created_by=self.owner,
            advisor=self.advisor,
        )
        project.team.add(self.owner, self.team_member)
        capstone_project = CapstoneProject.objects.create(project=project, term=term)
        checkpoint = CapstoneCheckpoint.objects.create(
            capstone_project=capstone_project,
            kind=CapstoneCheckpoint.Kind.FIRST_REVIEW,
            due_at=due_at,
        )
        task = CapstoneTask.objects.create(
            capstone_project=capstone_project,
            checkpoint=checkpoint,
            created_by=self.advisor,
            title='Private dosya teslimi',
            instructions='Dosyayı teslim edin.',
            due_at=due_at,
        )
        with patch('capstone.models.timezone.now', return_value=due_at - timedelta(hours=1)):
            attempt = CapstoneSubmissionAttempt.objects.create(
                task=task,
                submitted_by=self.owner,
                attempt_number=1,
            )
        self.submission_file = CapstoneSubmissionFile.objects.create(
            submission_attempt=attempt,
            file=SimpleUploadedFile('ödev raporu.pdf', self.FILE_CONTENT),
        )
        self.url = reverse(
            'capstone:submission_file_download',
            args=[self.submission_file.pk],
        )

    def tearDown(self):
        self.file_field.storage = self.original_storage
        self.private_directory.cleanup()

    def create_user(self, username, user_type, **fields):
        user = User.objects.create_user(username, password='StrongPassword123!', **fields)
        user.profile.user_type = user_type
        user.profile.class_level = '4' if user_type in {'student', 'staff_student'} else None
        user.profile.save(update_fields=['user_type', 'class_level'])
        return user

    def get_as(self, user):
        self.client.force_login(user)
        return self.client.get(self.url)

    def response_content(self, response):
        try:
            return b''.join(response.streaming_content)
        finally:
            response.close()

    def test_owner_can_download_file(self):
        response = self.get_as(self.owner)

        self.assertEqual(response.status_code, 200)
        response.close()

    def test_inactive_owner_cannot_download_file(self):
        self.owner.is_active = False
        self.owner.save(update_fields=['is_active'])
        self.assertEqual(self.get_as(self.owner).status_code, 404)

    def test_assigned_active_teacher_advisor_can_download_file(self):
        response = self.get_as(self.advisor)

        self.assertEqual(response.status_code, 200)
        response.close()

    def test_django_staff_and_superuser_can_download_file(self):
        for user in (self.staff, self.superuser):
            with self.subTest(user=user.username):
                response = self.get_as(user)
                self.assertEqual(response.status_code, 200)
                response.close()

    def test_team_only_user_gets_not_found(self):
        self.assertEqual(self.get_as(self.team_member).status_code, 404)

    def test_unrelated_student_gets_not_found(self):
        self.assertEqual(self.get_as(self.unrelated_student).status_code, 404)

    def test_unrelated_teacher_gets_not_found(self):
        self.assertEqual(self.get_as(self.unrelated_teacher).status_code, 404)

    def test_anonymous_user_gets_not_found_without_login_redirect(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)
        self.assertNotIn('Location', response)

    def test_inactive_or_non_teacher_assigned_advisor_gets_not_found(self):
        self.advisor.is_active = False
        self.advisor.save(update_fields=['is_active'])
        self.assertEqual(self.get_as(self.advisor).status_code, 404)

        self.advisor.is_active = True
        self.advisor.save(update_fields=['is_active'])
        self.advisor.profile.user_type = 'student'
        self.advisor.profile.class_level = '4'
        self.advisor.profile.save(update_fields=['user_type', 'class_level'])
        self.assertEqual(self.get_as(self.advisor).status_code, 404)

    def test_invalid_file_id_returns_not_found(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse('capstone:submission_file_download', args=[self.submission_file.pk + 9999])
        )

        self.assertEqual(response.status_code, 404)

    def test_missing_physical_file_returns_controlled_not_found(self):
        self.submission_file.file.storage.delete(self.submission_file.file.name)

        response = self.get_as(self.owner)

        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, self.submission_file.file.name, status_code=404)

    def test_response_streams_correct_private_file_content(self):
        response = self.get_as(self.owner)

        self.assertEqual(self.response_content(response), self.FILE_CONTENT)

    def test_content_disposition_is_attachment_with_safe_unicode_filename(self):
        response = self.get_as(self.owner)
        disposition = response['Content-Disposition']

        self.assertTrue(disposition.startswith('attachment;'))
        self.assertIn("filename*=utf-8''", disposition.lower())
        self.assertNotIn('\r', disposition)
        self.assertNotIn('\n', disposition)
        response.close()

    def test_security_and_private_cache_headers_are_set(self):
        response = self.get_as(self.owner)

        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['Content-Security-Policy'], "sandbox; default-src 'none'")
        response.close()

    def test_response_does_not_redirect_to_public_media(self):
        response = self.get_as(self.owner)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Location', response)
        response.close()

    def test_post_is_not_allowed(self):
        self.client.force_login(self.owner)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 405)

    def test_private_filesystem_path_is_not_exposed(self):
        response = self.get_as(self.owner)
        headers = '\n'.join(f'{key}: {value}' for key, value in response.items())
        body = self.response_content(response)

        self.assertNotIn(str(Path(self.private_directory.name)), headers)
        self.assertNotIn(str(Path(self.private_directory.name)).encode(), body)
