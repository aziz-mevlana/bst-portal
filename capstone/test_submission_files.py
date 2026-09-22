from datetime import datetime, timedelta, timezone as datetime_timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.test import TestCase

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


class CapstoneSubmissionFileModelTests(TestCase):
    def setUp(self):
        self.private_directory = TemporaryDirectory()
        self.file_field = CapstoneSubmissionFile._meta.get_field('file')
        self.original_storage = self.file_field.storage
        self.file_field.storage = PrivateFileSystemStorage(location=self.private_directory.name)

        self.owner = self.create_user('file-owner', 'student')
        self.advisor = self.create_user('file-advisor', 'teacher')
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
            title='Teslim dosyası projesi',
            created_by=self.owner,
            advisor=self.advisor,
        )
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
            title='Dosya teslimi',
            instructions='Çalışma dosyanızı teslim edin.',
            due_at=due_at,
        )
        with patch('capstone.models.timezone.now', return_value=due_at - timedelta(hours=1)):
            self.attempt = CapstoneSubmissionAttempt.objects.create(
                task=task,
                submitted_by=self.owner,
                attempt_number=1,
            )
            self.other_attempt = CapstoneSubmissionAttempt.objects.create(
                task=task,
                submitted_by=self.owner,
                attempt_number=2,
            )

    def tearDown(self):
        self.file_field.storage = self.original_storage
        self.private_directory.cleanup()

    def create_user(self, username, user_type):
        user = User.objects.create_user(username, password='StrongPassword123!')
        user.profile.user_type = user_type
        user.profile.class_level = '4' if user_type in {'student', 'staff_student'} else None
        user.profile.save(update_fields=['user_type', 'class_level'])
        return user

    def create_file(self, *, name='rapor.pdf', content=b'capstone-file', **overrides):
        values = {
            'submission_attempt': self.attempt,
            'file': ContentFile(content, name=name),
        }
        values.update(overrides)
        return CapstoneSubmissionFile.objects.create(**values)

    def test_valid_file_is_saved(self):
        submission_file = self.create_file()

        self.assertTrue(submission_file.pk)
        self.assertTrue(Path(submission_file.file.path).is_file())

    def test_submission_attempt_relationship_is_saved(self):
        submission_file = self.create_file()

        self.assertEqual(submission_file.submission_attempt, self.attempt)
        self.assertEqual(self.attempt.files.get(), submission_file)

    def test_size_bytes_is_derived_from_uploaded_file(self):
        content = b'1234567890'

        submission_file = self.create_file(content=content)

        self.assertEqual(submission_file.size_bytes, len(content))

    def test_caller_cannot_supply_fake_size_bytes(self):
        submission_file = self.create_file(content=b'actual', size_bytes=999999)

        self.assertEqual(submission_file.size_bytes, 6)

    def test_original_name_is_normalized_to_basename(self):
        submission_file = self.create_file(name='../../folder/tez-raporu.pdf')

        self.assertEqual(submission_file.original_name, 'tez-raporu.pdf')

    def test_path_traversal_is_not_reflected_in_storage_name(self):
        submission_file = self.create_file(name=r'..\..\secret.pdf')

        self.assertEqual(submission_file.original_name, 'secret.pdf')
        self.assertNotIn('..', submission_file.file.name)
        self.assertNotIn('secret.pdf', submission_file.file.name)
        self.assertTrue(submission_file.file.name.startswith('submissions/'))

    def test_storage_filename_is_random_and_collision_safe(self):
        first = self.create_file(name='same-name.pdf')
        second = self.create_file(
            name='same-name.pdf',
            submission_attempt=self.other_attempt,
        )

        self.assertNotEqual(first.file.name, second.file.name)
        self.assertNotIn('same-name.pdf', first.file.name)
        self.assertNotIn('same-name.pdf', second.file.name)

    def test_private_file_has_no_public_media_url(self):
        submission_file = self.create_file()

        self.assertIsNone(submission_file.file.storage.base_url)
        with self.assertRaises(NotImplementedError):
            _ = submission_file.file.url

    def test_saved_file_cannot_be_replaced(self):
        submission_file = self.create_file()
        original_path = submission_file.file.name
        submission_file.file = ContentFile(b'replacement', name='replacement.pdf')

        with self.assertRaises(ValidationError):
            submission_file.save()

        submission_file.refresh_from_db()
        self.assertEqual(submission_file.file.name, original_path)

    def test_submission_attempt_cannot_be_changed(self):
        submission_file = self.create_file()
        submission_file.submission_attempt = self.other_attempt

        with self.assertRaises(ValidationError):
            submission_file.save()

    def test_original_name_cannot_be_changed(self):
        submission_file = self.create_file()
        submission_file.original_name = 'degistirildi.pdf'

        with self.assertRaises(ValidationError):
            submission_file.save()

    def test_direct_save_cannot_bypass_required_file_invariant(self):
        submission_file = CapstoneSubmissionFile(
            submission_attempt=self.attempt,
            original_name='fake.pdf',
            size_bytes=123,
        )

        with self.assertRaises(ValidationError):
            submission_file.save()

        self.assertIsNone(submission_file.pk)
        self.assertEqual(submission_file.original_name, '')
        self.assertEqual(submission_file.size_bytes, 0)
