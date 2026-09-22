from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from projects.models import Project, ProjectType

from .models import (
    CapstoneCheckpoint,
    CapstoneProject,
    CapstoneSubmissionAttempt,
    CapstoneTask,
    CapstoneTerm,
)


class CapstoneSubmissionAttemptModelTests(TestCase):
    def setUp(self):
        self.owner = self.create_user('submission-owner', 'student')
        self.advisor = self.create_user('submission-advisor', 'teacher')
        self.team_member = self.create_user('submission-team-member', 'student')
        self.unrelated_student = self.create_user('submission-other-student', 'student')
        self.unrelated_teacher = self.create_user('submission-other-teacher', 'teacher')
        self.staff = self.create_user('submission-staff', 'student', is_staff=True)
        self.superuser = self.create_user('submission-superuser', 'student', is_superuser=True)

        self.on_time = datetime(2026, 10, 1, 11, 59, tzinfo=datetime_timezone.utc)
        self.due_at = datetime(2026, 10, 1, 12, 0, tzinfo=datetime_timezone.utc)
        starts_at = datetime(2026, 9, 1, 9, 0, tzinfo=datetime_timezone.utc)
        self.term = CapstoneTerm.objects.create(
            academic_year='2026-2027',
            semester=CapstoneTerm.Semester.FALL,
            starts_at=starts_at,
            midterm_at=starts_at + timedelta(weeks=8),
            final_at=starts_at + timedelta(weeks=16),
            is_active=True,
        )
        project = Project.objects.create(
            project_type=ProjectType.objects.get(code='CAPSTONE'),
            title='Teslim denemesi projesi',
            created_by=self.owner,
            advisor=self.advisor,
        )
        project.team.add(self.owner, self.team_member)
        self.capstone_project = CapstoneProject.objects.create(project=project, term=self.term)
        self.checkpoint = CapstoneCheckpoint.objects.create(
            capstone_project=self.capstone_project,
            kind=CapstoneCheckpoint.Kind.FIRST_REVIEW,
            due_at=self.due_at,
        )
        self.task = self.create_task('İlk teslim')
        self.other_task = self.create_task('İkinci teslim')

    def create_user(self, username, user_type, **fields):
        user = User.objects.create_user(username, password='StrongPassword123!', **fields)
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
            instructions='Belirtilen çalışmayı teslim edin.',
            required_file_count=1,
            due_at=self.due_at,
        )

    def create_attempt(self, *, submitted_at=None, **overrides):
        values = {
            'task': self.task,
            'submitted_by': self.owner,
            'attempt_number': 1,
        }
        values.update(overrides)
        submitted_at = submitted_at or self.on_time
        with patch('capstone.models.timezone.now', return_value=submitted_at):
            return CapstoneSubmissionAttempt.objects.create(**values)

    def test_project_owner_can_create_submission_attempt(self):
        attempt = self.create_attempt()

        self.assertEqual(attempt.submitted_by, self.owner)
        self.assertEqual(attempt.task, self.task)

    def test_team_only_user_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.create_attempt(submitted_by=self.team_member)

    def test_unrelated_student_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.create_attempt(submitted_by=self.unrelated_student)

    def test_unrelated_teacher_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.create_attempt(submitted_by=self.unrelated_teacher)

    def test_assigned_advisor_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.create_attempt(submitted_by=self.advisor)

    def test_django_staff_and_superuser_cannot_submit_for_student(self):
        for user in (self.staff, self.superuser):
            with self.subTest(user=user.username), self.assertRaises(ValidationError):
                self.create_attempt(submitted_by=user)

    def test_zero_attempt_number_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.create_attempt(attempt_number=0)

    def test_duplicate_attempt_number_for_same_task_is_rejected(self):
        self.create_attempt()

        with self.assertRaises(ValidationError):
            self.create_attempt()

    def test_different_attempt_number_for_same_task_is_accepted(self):
        self.create_attempt()

        second = self.create_attempt(attempt_number=2)

        self.assertEqual(second.attempt_number, 2)

    def test_same_attempt_number_for_different_task_is_accepted(self):
        self.create_attempt()

        other = self.create_attempt(task=self.other_task)

        self.assertEqual(other.attempt_number, 1)

    def test_submission_at_or_before_due_date_is_not_late(self):
        for index, submitted_at in enumerate((self.on_time, self.due_at), start=1):
            with self.subTest(submitted_at=submitted_at):
                attempt = self.create_attempt(
                    submitted_at=submitted_at,
                    attempt_number=index,
                )
                self.assertFalse(attempt.is_late)

    def test_submission_after_due_date_is_late(self):
        attempt = self.create_attempt(submitted_at=self.due_at + timedelta(microseconds=1))

        self.assertTrue(attempt.is_late)

    def test_caller_cannot_manipulate_is_late(self):
        on_time = self.create_attempt(is_late=True)
        late = self.create_attempt(
            submitted_at=self.due_at + timedelta(seconds=1),
            attempt_number=2,
            is_late=False,
        )

        self.assertFalse(on_time.is_late)
        self.assertTrue(late.is_late)

    def test_saved_attempt_fields_are_immutable(self):
        attempt = self.create_attempt()
        immutable_changes = {
            'task': self.other_task,
            'submitted_by': self.unrelated_student,
            'attempt_number': 2,
            'submitted_at': self.on_time + timedelta(minutes=1),
            'is_late': True,
        }

        for field, value in immutable_changes.items():
            with self.subTest(field=field):
                setattr(attempt, field, value)
                with self.assertRaises(ValidationError):
                    attempt.save()
                attempt.refresh_from_db()

    def test_direct_save_cannot_bypass_submission_invariants(self):
        attempt = CapstoneSubmissionAttempt(
            task=self.task,
            submitted_by=self.team_member,
            attempt_number=0,
            is_late=True,
        )

        with patch('capstone.models.timezone.now', return_value=self.on_time):
            with self.assertRaises(ValidationError):
                attempt.save()

        self.assertIsNone(attempt.pk)
        self.assertFalse(attempt.is_late)
