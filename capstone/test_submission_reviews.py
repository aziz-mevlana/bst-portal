from datetime import datetime, timedelta, timezone as datetime_timezone
from queue import Queue
from threading import Barrier, Thread
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase

from projects.models import Project, ProjectType

from .models import (
    CapstoneCheckpoint,
    CapstoneProject,
    CapstoneSubmissionAttempt,
    CapstoneSubmissionReview,
    CapstoneTask,
    CapstoneTerm,
)
from .services import review_capstone_submission


class SubmissionReviewFixtureMixin:
    def setUp(self):
        super().setUp()
        self.owner = self.create_user('review-owner', 'student')
        self.advisor = self.create_user('review-advisor', 'teacher')
        self.team_member = self.create_user('review-team', 'student')
        self.unrelated_student = self.create_user('review-student', 'student')
        self.unrelated_teacher = self.create_user('review-teacher', 'teacher')
        self.staff = self.create_user('review-staff', 'student', is_staff=True)
        self.superuser = self.create_user('review-superuser', 'student', is_superuser=True)

        starts_at = datetime(2026, 9, 1, 9, 0, tzinfo=datetime_timezone.utc)
        self.reviewed_at = datetime(2026, 10, 1, 13, 0, tzinfo=datetime_timezone.utc)
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
            title='Submission review projesi',
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
            title='Review görevi',
            instructions='Teslimi değerlendirin.',
            due_at=due_at,
        )
        with patch('capstone.models.timezone.now', return_value=due_at - timedelta(hours=1)):
            self.attempt = CapstoneSubmissionAttempt.objects.create(
                task=task,
                submitted_by=self.owner,
                attempt_number=1,
            )

    def create_user(self, username, user_type, **fields):
        user = User.objects.create_user(username, password='StrongPassword123!', **fields)
        user.profile.user_type = user_type
        user.profile.class_level = '4' if user_type in {'student', 'staff_student'} else None
        user.profile.save(update_fields=['user_type', 'class_level'])
        return user

    def review(self, *, attempt=None, reviewer=None, decision=None, feedback='Açıklamalı değerlendirme.'):
        with patch('capstone.models.timezone.now', return_value=self.reviewed_at):
            return review_capstone_submission(
                submission_attempt=attempt or self.attempt,
                reviewer=reviewer or self.advisor,
                decision=decision or CapstoneSubmissionReview.Decision.ACCEPTED,
                feedback=feedback,
            )

    def create_second_attempt(self):
        with patch(
            'capstone.models.timezone.now',
            return_value=self.attempt.submitted_at + timedelta(hours=1),
        ):
            return CapstoneSubmissionAttempt.objects.create(
                task=self.attempt.task,
                submitted_by=self.owner,
                attempt_number=2,
            )


class CapstoneSubmissionReviewTests(SubmissionReviewFixtureMixin, TestCase):
    def test_assigned_active_advisor_can_create_review(self):
        review = self.review()

        self.assertEqual(review.reviewed_by, self.advisor)

    def test_django_staff_can_create_review(self):
        review = self.review(reviewer=self.staff)

        self.assertEqual(review.reviewed_by, self.staff)

    def test_superuser_can_create_review(self):
        review = self.review(reviewer=self.superuser)

        self.assertEqual(review.reviewed_by, self.superuser)

    def test_unauthorized_users_cannot_create_review(self):
        users = (
            self.owner,
            self.team_member,
            self.unrelated_teacher,
            self.unrelated_student,
        )
        for user in users:
            with self.subTest(user=user.username), self.assertRaises(ValidationError):
                self.review(reviewer=user)
        self.assertFalse(CapstoneSubmissionReview.objects.exists())

    def test_inactive_advisor_cannot_create_review(self):
        self.advisor.is_active = False
        self.advisor.save(update_fields=['is_active'])

        with self.assertRaises(ValidationError):
            self.review()

    def test_advisor_who_lost_teacher_role_cannot_create_review(self):
        self.advisor.profile.user_type = 'student'
        self.advisor.profile.class_level = '4'
        self.advisor.profile.save(update_fields=['user_type', 'class_level'])

        with self.assertRaises(ValidationError):
            self.review()

    def test_all_defined_decisions_are_accepted(self):
        decisions = (
            CapstoneSubmissionReview.Decision.ACCEPTED,
            CapstoneSubmissionReview.Decision.REVISION_REQUIRED,
            CapstoneSubmissionReview.Decision.REJECTED,
        )
        for decision in decisions:
            with self.subTest(decision=decision):
                review = self.review(decision=decision)
                self.assertEqual(review.decision, decision)
                review.delete()

    def test_invalid_decision_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.review(decision='MANIPULATED')

    def test_blank_and_whitespace_only_feedback_are_rejected(self):
        for feedback in ('', '   \n\t  '):
            with self.subTest(feedback=repr(feedback)), self.assertRaises(ValidationError):
                self.review(feedback=feedback)

    def test_reviewed_at_is_server_assigned_and_reviewer_is_saved(self):
        review = self.review(reviewer=self.staff)

        self.assertEqual(review.reviewed_at, self.reviewed_at)
        self.assertEqual(review.reviewed_by, self.staff)

    def test_same_attempt_cannot_be_reviewed_twice(self):
        self.review()

        with self.assertRaises(ValidationError):
            self.review(reviewer=self.staff)

        self.assertEqual(CapstoneSubmissionReview.objects.count(), 1)

    def test_different_attempts_keep_separate_review_history(self):
        first = self.review(decision=CapstoneSubmissionReview.Decision.REVISION_REQUIRED)
        second_attempt = self.create_second_attempt()
        second = self.review(
            attempt=second_attempt,
            decision=CapstoneSubmissionReview.Decision.ACCEPTED,
        )

        self.assertNotEqual(first.submission_attempt_id, second.submission_attempt_id)
        self.assertEqual(CapstoneSubmissionReview.objects.count(), 2)

    def test_saved_review_fields_are_immutable(self):
        review = self.review()
        second_attempt = self.create_second_attempt()
        immutable_changes = {
            'submission_attempt': second_attempt,
            'reviewed_by': self.staff,
            'decision': CapstoneSubmissionReview.Decision.REJECTED,
            'feedback': 'Değiştirilen geri bildirim.',
            'reviewed_at': self.reviewed_at + timedelta(minutes=1),
        }

        for field, value in immutable_changes.items():
            with self.subTest(field=field):
                setattr(review, field, value)
                with self.assertRaises(ValidationError):
                    review.save()
                review.refresh_from_db()

    def test_direct_orm_save_cannot_bypass_model_invariants(self):
        review = CapstoneSubmissionReview(
            submission_attempt=self.attempt,
            reviewed_by=self.owner,
            decision='MANIPULATED',
            feedback='   ',
        )

        with patch('capstone.models.timezone.now', return_value=self.reviewed_at):
            with self.assertRaises(ValidationError):
                review.save()

        self.assertIsNone(review.pk)


class CapstoneSubmissionReviewConcurrencyTests(SubmissionReviewFixtureMixin, TransactionTestCase):
    reset_sequences = True

    @skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row-lock semantics required.')
    def test_concurrent_reviewers_create_only_one_review(self):
        barrier = Barrier(2)
        results = Queue()

        def review_in_thread(reviewer_id):
            close_old_connections()
            try:
                attempt = CapstoneSubmissionAttempt.objects.get(pk=self.attempt.pk)
                reviewer = User.objects.get(pk=reviewer_id)
                barrier.wait()
                review_capstone_submission(
                    submission_attempt=attempt,
                    reviewer=reviewer,
                    decision=CapstoneSubmissionReview.Decision.ACCEPTED,
                    feedback='Eşzamanlı değerlendirme.',
                )
                results.put('created')
            except ValidationError:
                results.put('validation_error')
            except Exception as exc:
                results.put(exc)
            finally:
                close_old_connections()

        threads = [
            Thread(target=review_in_thread, args=(reviewer.pk,))
            for reviewer in (self.advisor, self.staff)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        outcomes = [results.get_nowait() for _ in range(2)]
        self.assertCountEqual(outcomes, ['created', 'validation_error'])
        self.assertEqual(
            CapstoneSubmissionReview.objects.filter(submission_attempt=self.attempt).count(),
            1,
        )
