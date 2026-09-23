from datetime import datetime, timedelta, timezone as datetime_timezone
from queue import Queue
from tempfile import TemporaryDirectory
from threading import Barrier, Thread
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection, connections
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
from .workflow import (
    CheckpointProgress,
    TaskWorkflowState,
    get_checkpoint_progress,
    get_task_workflow_state,
    is_checkpoint_overdue,
    is_task_overdue,
)


class WorkflowFixtureMixin:
    def setUp(self):
        super().setUp()
        self.private_directory = TemporaryDirectory()
        self.file_field = CapstoneSubmissionFile._meta.get_field('file')
        self.original_storage = self.file_field.storage
        self.file_field.storage = PrivateFileSystemStorage(location=self.private_directory.name)

        self.owner = self.create_user('workflow-owner', 'student')
        self.advisor = self.create_user('workflow-advisor', 'teacher')
        starts_at = datetime(2026, 9, 1, 9, 0, tzinfo=datetime_timezone.utc)
        self.due_at = datetime(2026, 10, 1, 12, 0, tzinfo=datetime_timezone.utc)
        term = CapstoneTerm.objects.create(
            academic_year='2026-2027',
            semester=CapstoneTerm.Semester.FALL,
            starts_at=starts_at,
            midterm_at=starts_at + timedelta(weeks=8),
            final_at=starts_at + timedelta(weeks=16),
            is_active=True,
        )
        project = Project.objects.create(
            project_type=ProjectType.objects.get_or_create(
                code='CAPSTONE', defaults={'name': 'Bitirme Projesi', 'slug': 'bitirme-projesi'}
            )[0],
            title='Workflow projesi',
            created_by=self.owner,
            advisor=self.advisor,
        )
        project.team.add(self.owner)
        self.capstone_project = CapstoneProject.objects.create(project=project, term=term)
        self.checkpoint = CapstoneCheckpoint.objects.create(
            capstone_project=self.capstone_project,
            kind=CapstoneCheckpoint.Kind.FIRST_REVIEW,
            due_at=self.due_at,
        )
        self.empty_checkpoint = CapstoneCheckpoint.objects.create(
            capstone_project=self.capstone_project,
            kind=CapstoneCheckpoint.Kind.MIDTERM_REVIEW,
            due_at=self.due_at + timedelta(weeks=4),
        )
        self.task = self.create_task('Ana workflow görevi')

    def tearDown(self):
        self.file_field.storage = self.original_storage
        self.private_directory.cleanup()
        super().tearDown()

    def create_user(self, username, user_type):
        user = User.objects.create_user(username, password='StrongPassword123!')
        user.profile.user_type = user_type
        user.profile.class_level = '4' if user_type in {'student', 'staff_student'} else None
        user.profile.save(update_fields=['user_type', 'class_level'])
        return user

    def create_task(self, title):
        return CapstoneTask.objects.create(
            capstone_project=self.capstone_project,
            checkpoint=self.checkpoint,
            created_by=self.advisor,
            title=title,
            instructions='Workflow teslimini hazırlayın.',
            required_file_count=1,
            due_at=self.due_at,
        )

    def submit(self, *, task=None, submitted_at=None, prefix='workflow'):
        submitted_at = submitted_at or self.due_at - timedelta(minutes=1)
        with patch('capstone.models.timezone.now', return_value=submitted_at):
            return create_capstone_submission(
                task=task or self.task,
                student=self.owner,
                files=[SimpleUploadedFile(f'{prefix}.bin', b'workflow-content')],
            )

    def review(self, attempt, decision):
        return review_capstone_submission(
            submission_attempt=attempt,
            reviewer=self.advisor,
            decision=decision,
            feedback='Workflow değerlendirmesi.',
        )


class CapstoneWorkflowTests(WorkflowFixtureMixin, TestCase):
    def test_task_without_attempt_is_not_submitted(self):
        self.assertEqual(
            get_task_workflow_state(self.task),
            TaskWorkflowState.NOT_SUBMITTED,
        )

    def test_latest_unreviewed_attempt_is_awaiting_review(self):
        self.submit()

        self.assertEqual(
            get_task_workflow_state(self.task),
            TaskWorkflowState.AWAITING_REVIEW,
        )

    def test_latest_review_decision_determines_task_state(self):
        decisions = (
            (CapstoneSubmissionReview.Decision.REVISION_REQUIRED, TaskWorkflowState.REVISION_REQUIRED),
            (CapstoneSubmissionReview.Decision.REJECTED, TaskWorkflowState.REJECTED),
            (CapstoneSubmissionReview.Decision.ACCEPTED, TaskWorkflowState.ACCEPTED),
        )
        for decision, expected_state in decisions:
            with self.subTest(decision=decision):
                attempt = self.submit(prefix=decision.lower())
                self.review(attempt, decision)
                self.assertEqual(get_task_workflow_state(self.task), expected_state)
                attempt.review.delete()
                attempt.delete()

    def test_old_review_does_not_override_latest_attempt_state(self):
        first = self.submit(prefix='first')
        self.review(first, CapstoneSubmissionReview.Decision.REVISION_REQUIRED)
        second = self.submit(prefix='second')

        self.assertEqual(second.attempt_number, 2)
        self.assertEqual(get_task_workflow_state(self.task), TaskWorkflowState.AWAITING_REVIEW)

    def test_first_submission_is_allowed(self):
        attempt = self.submit()

        self.assertEqual(attempt.attempt_number, 1)

    def test_unreviewed_attempt_blocks_new_submission(self):
        self.submit(prefix='first')

        with self.assertRaises(ValidationError):
            self.submit(prefix='blocked')

        self.assertEqual(self.task.submission_attempts.count(), 1)

    def test_revision_required_allows_next_numbered_attempt(self):
        first = self.submit(prefix='first')
        self.review(first, CapstoneSubmissionReview.Decision.REVISION_REQUIRED)

        second = self.submit(prefix='second')

        self.assertEqual(second.attempt_number, 2)

    def test_rejected_allows_next_attempt(self):
        first = self.submit(prefix='first')
        self.review(first, CapstoneSubmissionReview.Decision.REJECTED)

        second = self.submit(prefix='second')

        self.assertEqual(second.attempt_number, 2)

    def test_accepted_blocks_new_submission(self):
        first = self.submit(prefix='first')
        self.review(first, CapstoneSubmissionReview.Decision.ACCEPTED)

        with self.assertRaises(ValidationError):
            self.submit(prefix='blocked')

        self.assertEqual(self.task.submission_attempts.count(), 1)

    def test_latest_attempt_can_be_reviewed_and_duplicate_stays_blocked(self):
        attempt = self.submit()
        review = self.review(attempt, CapstoneSubmissionReview.Decision.ACCEPTED)

        self.assertEqual(review.submission_attempt, attempt)
        with self.assertRaises(ValidationError):
            self.review(attempt, CapstoneSubmissionReview.Decision.REJECTED)

    def test_stale_attempt_cannot_be_reviewed(self):
        with patch('capstone.models.timezone.now', return_value=self.due_at - timedelta(hours=2)):
            stale_attempt = CapstoneSubmissionAttempt.objects.create(
                task=self.task,
                submitted_by=self.owner,
                attempt_number=1,
            )
            CapstoneSubmissionAttempt.objects.create(
                task=self.task,
                submitted_by=self.owner,
                attempt_number=2,
            )

        with self.assertRaises(ValidationError):
            self.review(stale_attempt, CapstoneSubmissionReview.Decision.ACCEPTED)

        self.assertFalse(CapstoneSubmissionReview.objects.exists())

    def test_task_overdue_is_separate_from_workflow_state(self):
        self.assertFalse(is_task_overdue(self.task, now=self.due_at - timedelta(seconds=1)))
        self.assertTrue(is_task_overdue(self.task, now=self.due_at + timedelta(seconds=1)))

        attempt = self.submit()
        self.review(attempt, CapstoneSubmissionReview.Decision.ACCEPTED)

        self.assertFalse(is_task_overdue(self.task, now=self.due_at + timedelta(days=10)))

    def test_checkpoint_without_tasks_is_not_started(self):
        self.assertEqual(
            get_checkpoint_progress(self.empty_checkpoint),
            CheckpointProgress.NOT_STARTED,
        )

    def test_checkpoint_with_incomplete_task_is_in_progress(self):
        self.assertEqual(
            get_checkpoint_progress(self.checkpoint),
            CheckpointProgress.IN_PROGRESS,
        )

    def test_checkpoint_is_completed_when_all_tasks_are_accepted(self):
        attempt = self.submit()
        self.review(attempt, CapstoneSubmissionReview.Decision.ACCEPTED)

        self.assertEqual(
            get_checkpoint_progress(self.checkpoint),
            CheckpointProgress.COMPLETED,
        )

    def test_checkpoint_with_any_incomplete_task_is_in_progress(self):
        attempt = self.submit()
        self.review(attempt, CapstoneSubmissionReview.Decision.ACCEPTED)
        self.create_task('Henüz tamamlanmamış görev')

        self.assertEqual(
            get_checkpoint_progress(self.checkpoint),
            CheckpointProgress.IN_PROGRESS,
        )

    def test_checkpoint_overdue_depends_on_derived_completion(self):
        self.assertFalse(
            is_checkpoint_overdue(self.checkpoint, now=self.due_at - timedelta(seconds=1))
        )
        self.assertTrue(
            is_checkpoint_overdue(self.checkpoint, now=self.due_at + timedelta(seconds=1))
        )
        attempt = self.submit()
        self.review(attempt, CapstoneSubmissionReview.Decision.ACCEPTED)
        self.assertFalse(
            is_checkpoint_overdue(self.checkpoint, now=self.due_at + timedelta(days=10))
        )


class CapstoneWorkflowConcurrencyTests(WorkflowFixtureMixin, TransactionTestCase):
    reset_sequences = True

    @skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row-lock semantics required.')
    def test_review_and_new_submission_race_keeps_consistent_task_state(self):
        first_attempt = self.submit(prefix='first')
        barrier = Barrier(2)
        results = Queue()

        def review_in_thread():
            close_old_connections()
            try:
                attempt = CapstoneSubmissionAttempt.objects.get(pk=first_attempt.pk)
                reviewer = User.objects.get(pk=self.advisor.pk)
                barrier.wait()
                review_capstone_submission(
                    submission_attempt=attempt,
                    reviewer=reviewer,
                    decision=CapstoneSubmissionReview.Decision.REVISION_REQUIRED,
                    feedback='Yeni teslim gerekli.',
                )
                results.put('review_created')
            except Exception as exc:
                results.put(exc)
            finally:
                connections.close_all()

        def submit_in_thread():
            close_old_connections()
            try:
                task = CapstoneTask.objects.get(pk=self.task.pk)
                student = User.objects.get(pk=self.owner.pk)
                barrier.wait()
                create_capstone_submission(
                    task=task,
                    student=student,
                    files=[SimpleUploadedFile('concurrent.bin', b'concurrent-content')],
                )
                results.put('submission_created')
            except ValidationError:
                results.put('submission_rejected')
            except Exception as exc:
                results.put(exc)
            finally:
                connections.close_all()

        threads = [Thread(target=review_in_thread), Thread(target=submit_in_thread)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        outcomes = [results.get_nowait() for _ in range(2)]
        self.assertIn('review_created', outcomes)
        self.assertTrue(
            'submission_created' in outcomes or 'submission_rejected' in outcomes,
            outcomes,
        )
        self.assertFalse(any(isinstance(outcome, Exception) for outcome in outcomes))
        self.assertEqual(first_attempt.review.decision, CapstoneSubmissionReview.Decision.REVISION_REQUIRED)
        self.assertLessEqual(
            CapstoneSubmissionAttempt.objects.filter(
                task=self.task,
                review__isnull=True,
            ).count(),
            1,
        )
        self.assertIn(
            get_task_workflow_state(self.task),
            {TaskWorkflowState.REVISION_REQUIRED, TaskWorkflowState.AWAITING_REVIEW},
        )
