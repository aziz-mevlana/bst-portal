from datetime import datetime, timedelta, timezone as datetime_timezone
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
from threading import Barrier, Thread
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase

from projects.models import Project, ProjectType

from .models import (
    CapstoneCheckpoint,
    CapstoneProject,
    CapstoneSubmissionAttempt,
    CapstoneSubmissionFile,
    CapstoneSubmissionReview,
    CapstoneTask,
    CapstoneTerm,
)
from .services import create_capstone_submission, review_capstone_submission
from .storage import PrivateFileSystemStorage


class SubmissionServiceFixtureMixin:
    def setUp(self):
        super().setUp()
        self.private_directory = TemporaryDirectory()
        self.file_field = CapstoneSubmissionFile._meta.get_field('file')
        self.original_storage = self.file_field.storage
        self.file_field.storage = PrivateFileSystemStorage(location=self.private_directory.name)

        self.owner = self.create_user('service-owner', 'student')
        self.advisor = self.create_user('service-advisor', 'teacher')
        self.team_member = self.create_user('service-team-member', 'student')
        self.unrelated_student = self.create_user('service-other-student', 'student')
        self.staff = self.create_user('service-staff', 'student', is_staff=True)
        self.superuser = self.create_user('service-superuser', 'student', is_superuser=True)

        starts_at = datetime(2026, 9, 1, 9, 0, tzinfo=datetime_timezone.utc)
        self.due_at = starts_at + timedelta(weeks=4)
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
            title='Submission service projesi',
            created_by=self.owner,
            advisor=self.advisor,
        )
        project.team.add(self.owner, self.team_member)
        capstone_project = CapstoneProject.objects.create(project=project, term=term)
        checkpoint = CapstoneCheckpoint.objects.create(
            capstone_project=capstone_project,
            kind=CapstoneCheckpoint.Kind.FIRST_REVIEW,
            due_at=self.due_at,
        )
        self.task = self.create_task(
            capstone_project=capstone_project,
            checkpoint=checkpoint,
            title='Ana teslim görevi',
            required_file_count=2,
        )
        self.other_task = self.create_task(
            capstone_project=capstone_project,
            checkpoint=checkpoint,
            title='Diğer teslim görevi',
            required_file_count=1,
        )

    def tearDown(self):
        self.file_field.storage = self.original_storage
        self.private_directory.cleanup()
        super().tearDown()

    def create_user(self, username, user_type, **fields):
        user = User.objects.create_user(username, password='StrongPassword123!', **fields)
        user.profile.user_type = user_type
        user.profile.class_level = '4' if user_type in {'student', 'staff_student'} else None
        user.profile.save(update_fields=['user_type', 'class_level'])
        return user

    def create_task(self, *, capstone_project, checkpoint, title, required_file_count):
        return CapstoneTask.objects.create(
            capstone_project=capstone_project,
            checkpoint=checkpoint,
            created_by=self.advisor,
            title=title,
            instructions='Dosyaları eksiksiz teslim edin.',
            required_file_count=required_file_count,
            due_at=self.due_at,
        )

    def uploads(self, count, *, prefix='file', content=b'capstone-content'):
        return [
            SimpleUploadedFile(f'{prefix}-{index}.bin', content)
            for index in range(1, count + 1)
        ]

    def submit(self, *, task=None, student=None, files=None, submitted_at=None):
        submitted_at = submitted_at or self.due_at - timedelta(minutes=1)
        with patch('capstone.models.timezone.now', return_value=submitted_at):
            return create_capstone_submission(
                task=task or self.task,
                student=student or self.owner,
                files=self.uploads(2) if files is None else files,
            )


class CapstoneSubmissionServiceTests(SubmissionServiceFixtureMixin, TestCase):
    def test_owner_with_exact_file_count_creates_first_attempt(self):
        attempt = self.submit()

        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(attempt.submitted_by, self.owner)
        self.assertEqual(attempt.files.count(), 2)

    def test_second_submission_gets_attempt_number_two(self):
        first = self.submit()
        review_capstone_submission(
            submission_attempt=first,
            reviewer=self.advisor,
            decision=CapstoneSubmissionReview.Decision.REVISION_REQUIRED,
            feedback='Yeni teslim gerekli.',
        )

        second = self.submit(files=self.uploads(2, prefix='second'))

        self.assertEqual(second.attempt_number, 2)

    def test_different_task_starts_its_own_attempt_sequence(self):
        self.submit()

        other = self.submit(task=self.other_task, files=self.uploads(1))

        self.assertEqual(other.attempt_number, 1)

    def test_too_few_files_rolls_back_without_attempt(self):
        with self.assertRaises(ValidationError):
            self.submit(files=self.uploads(1))

        self.assertFalse(CapstoneSubmissionAttempt.objects.exists())
        self.assertFalse(CapstoneSubmissionFile.objects.exists())

    def test_empty_file_list_is_rejected_without_attempt(self):
        with self.assertRaises(ValidationError):
            self.submit(files=[])

        self.assertFalse(CapstoneSubmissionAttempt.objects.exists())

    def test_too_many_files_rolls_back_without_attempt(self):
        with self.assertRaises(ValidationError):
            self.submit(files=self.uploads(3))

        self.assertFalse(CapstoneSubmissionAttempt.objects.exists())
        self.assertFalse(CapstoneSubmissionFile.objects.exists())

    def test_empty_file_is_rejected(self):
        files = self.uploads(1) + [SimpleUploadedFile('empty.bin', b'')]

        with self.assertRaises(ValidationError):
            self.submit(files=files)

        self.assertFalse(CapstoneSubmissionAttempt.objects.exists())

    def test_non_uploaded_file_object_is_rejected(self):
        files = self.uploads(1) + [ContentFile(b'content', name='not-upload.bin')]

        with self.assertRaises(ValidationError):
            self.submit(files=files)

        self.assertFalse(CapstoneSubmissionAttempt.objects.exists())

    def test_existing_generic_upload_size_limit_is_enforced(self):
        oversized = SimpleUploadedFile('oversized.bin', b'x')
        oversized.size = 20 * 1024 * 1024 + 1

        with self.assertRaises(ValidationError):
            self.submit(files=self.uploads(1) + [oversized])

        self.assertFalse(CapstoneSubmissionAttempt.objects.exists())

    def test_unrelated_student_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.submit(student=self.unrelated_student)

    def test_inactive_owner_is_rejected(self):
        self.owner.is_active = False
        self.owner.save(update_fields=['is_active'])

        with self.assertRaises(ValidationError):
            self.submit(student=self.owner)

    def test_team_only_student_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.submit(student=self.team_member)

    def test_assigned_advisor_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.submit(student=self.advisor)

    def test_django_staff_and_superuser_are_rejected(self):
        for user in (self.staff, self.superuser):
            with self.subTest(user=user.username), self.assertRaises(ValidationError):
                self.submit(student=user)

    def test_created_files_belong_to_created_attempt(self):
        attempt = self.submit()

        self.assertEqual(
            set(CapstoneSubmissionFile.objects.values_list('submission_attempt_id', flat=True)),
            {attempt.pk},
        )

    def test_file_metadata_is_derived_server_side(self):
        files = [
            SimpleUploadedFile('../report.bin', b'first'),
            SimpleUploadedFile('notes.bin', b'second-file'),
        ]

        attempt = self.submit(files=files)

        metadata = list(attempt.files.values_list('original_name', 'size_bytes'))
        self.assertEqual(metadata, [('report.bin', 5), ('notes.bin', 11)])
        self.assertTrue(all('/' not in name for name, _ in metadata))

    def test_late_submission_is_marked_late(self):
        attempt = self.submit(submitted_at=self.due_at + timedelta(microseconds=1))

        self.assertTrue(attempt.is_late)

    def test_on_time_submission_is_not_late(self):
        attempt = self.submit(submitted_at=self.due_at)

        self.assertFalse(attempt.is_late)

    def test_file_save_failure_rolls_back_database_and_private_files(self):
        real_save = CapstoneSubmissionFile.save
        save_count = 0

        def fail_after_second_file_save(instance, *args, **kwargs):
            nonlocal save_count
            save_count += 1
            result = real_save(instance, *args, **kwargs)
            if save_count == 2:
                raise ValidationError('Simüle edilen storage sonrası hata.')
            return result

        with patch.object(CapstoneSubmissionFile, 'save', new=fail_after_second_file_save):
            with self.assertRaises(ValidationError):
                self.submit()

        self.assertFalse(CapstoneSubmissionAttempt.objects.exists())
        self.assertFalse(CapstoneSubmissionFile.objects.exists())
        stored_files = [path for path in Path(self.private_directory.name).rglob('*') if path.is_file()]
        self.assertEqual(stored_files, [])


class CapstoneSubmissionConcurrencyTests(SubmissionServiceFixtureMixin, TransactionTestCase):
    reset_sequences = True

    @skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row-lock semantics required.')
    def test_concurrent_first_submissions_create_one_outstanding_attempt(self):
        barrier = Barrier(2)
        results = Queue()

        def submit_in_thread(index):
            close_old_connections()
            try:
                task = CapstoneTask.objects.get(pk=self.task.pk)
                student = User.objects.get(pk=self.owner.pk)
                barrier.wait()
                attempt = create_capstone_submission(
                    task=task,
                    student=student,
                    files=self.uploads(2, prefix=f'concurrent-{index}'),
                )
                results.put(('created', attempt.attempt_number))
            except ValidationError:
                results.put(('validation_error', None))
            except Exception as exc:
                results.put(('error', exc))
            finally:
                close_old_connections()

        threads = [Thread(target=submit_in_thread, args=(index,)) for index in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        outcomes = [results.get_nowait() for _ in range(2)]
        errors = [value for status, value in outcomes if status == 'error']
        self.assertEqual(errors, [])
        self.assertCountEqual([status for status, _ in outcomes], ['created', 'validation_error'])
        self.assertEqual(
            list(
                CapstoneSubmissionAttempt.objects.filter(task=self.task)
                .order_by('attempt_number')
                .values_list('attempt_number', flat=True)
            ),
            [1],
        )
