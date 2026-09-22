from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from projects.models import Project, ProjectType

from .models import CapstoneCheckpoint, CapstoneProject, CapstoneTerm
from .services import create_capstone_checkpoints


class CapstoneCheckpointServiceTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user('checkpoint-owner', password='StrongPassword123!')
        advisor = User.objects.create_user('checkpoint-advisor', password='StrongPassword123!')
        starts_at = timezone.now()
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
            title='Checkpoint Servis Testi',
            created_by=owner,
            advisor=advisor,
        )
        self.capstone_project = CapstoneProject.objects.create(project=project, term=self.term)

    def checkpoint_by_kind(self):
        return {
            checkpoint.kind: checkpoint
            for checkpoint in CapstoneCheckpoint.objects.filter(capstone_project=self.capstone_project)
        }

    def test_service_creates_all_checkpoint_kinds_in_deterministic_order(self):
        checkpoints = create_capstone_checkpoints(self.capstone_project)

        expected_kinds = [
            CapstoneCheckpoint.Kind.FIRST_REVIEW,
            CapstoneCheckpoint.Kind.MIDTERM_REVIEW,
            CapstoneCheckpoint.Kind.POST_MIDTERM_REVIEW,
            CapstoneCheckpoint.Kind.FINAL_REVIEW,
        ]
        self.assertEqual([checkpoint.kind for checkpoint in checkpoints], expected_kinds)
        self.assertEqual(self.capstone_project.checkpoints.count(), 4)

    def test_first_review_is_four_weeks_after_term_start(self):
        create_capstone_checkpoints(self.capstone_project)

        checkpoint = self.checkpoint_by_kind()[CapstoneCheckpoint.Kind.FIRST_REVIEW]
        self.assertEqual(checkpoint.due_at, self.term.starts_at + timedelta(weeks=4))

    def test_midterm_review_uses_term_midterm(self):
        create_capstone_checkpoints(self.capstone_project)

        checkpoint = self.checkpoint_by_kind()[CapstoneCheckpoint.Kind.MIDTERM_REVIEW]
        self.assertEqual(checkpoint.due_at, self.term.midterm_at)

    def test_post_midterm_review_is_four_weeks_after_midterm(self):
        create_capstone_checkpoints(self.capstone_project)

        checkpoint = self.checkpoint_by_kind()[CapstoneCheckpoint.Kind.POST_MIDTERM_REVIEW]
        self.assertEqual(checkpoint.due_at, self.term.midterm_at + timedelta(weeks=4))

    def test_final_review_uses_term_final(self):
        create_capstone_checkpoints(self.capstone_project)

        checkpoint = self.checkpoint_by_kind()[CapstoneCheckpoint.Kind.FINAL_REVIEW]
        self.assertEqual(checkpoint.due_at, self.term.final_at)

    def test_service_is_idempotent(self):
        first_result = create_capstone_checkpoints(self.capstone_project)
        second_result = create_capstone_checkpoints(self.capstone_project)

        self.assertEqual(self.capstone_project.checkpoints.count(), 4)
        self.assertEqual(
            [checkpoint.pk for checkpoint in second_result],
            [checkpoint.pk for checkpoint in first_result],
        )

    def test_first_review_after_midterm_creates_no_checkpoints(self):
        self.term.midterm_at = self.term.starts_at + timedelta(weeks=3)
        self.term.save(update_fields=['midterm_at', 'updated_at'])

        with self.assertRaises(ValidationError):
            create_capstone_checkpoints(self.capstone_project)

        self.assertFalse(self.capstone_project.checkpoints.exists())

    def test_post_midterm_review_after_final_creates_no_checkpoints(self):
        self.term.final_at = self.term.midterm_at + timedelta(weeks=3)
        self.term.save(update_fields=['final_at', 'updated_at'])

        with self.assertRaises(ValidationError):
            create_capstone_checkpoints(self.capstone_project)

        self.assertFalse(self.capstone_project.checkpoints.exists())
