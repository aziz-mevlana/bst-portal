from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from projects.models import Project, ProjectType

from .models import CapstoneCheckpoint, CapstoneProject, CapstoneTerm


class CapstoneModelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('capstone-owner', password='StrongPassword123!')
        self.advisor = User.objects.create_user('capstone-advisor', password='StrongPassword123!')
        self.capstone_type = ProjectType.objects.get(code='CAPSTONE')
        now = timezone.now()
        self.term = CapstoneTerm.objects.create(
            academic_year='2026-2027',
            semester=CapstoneTerm.Semester.FALL,
            starts_at=now,
            midterm_at=now + timedelta(days=60),
            final_at=now + timedelta(days=120),
            is_active=True,
        )

    def create_project(self, *, project_type=None, advisor=True):
        return Project.objects.create(
            project_type=project_type or self.capstone_type,
            title='Bitirme Projesi',
            created_by=self.owner,
            advisor=self.advisor if advisor else None,
        )

    def test_capstone_project_accepts_capstone_with_advisor(self):
        project = self.create_project()

        capstone_project = CapstoneProject.objects.create(project=project, term=self.term)

        self.assertEqual(capstone_project.project, project)
        self.assertEqual(project.capstone, capstone_project)

    def test_capstone_project_rejects_non_capstone_project(self):
        project = self.create_project(project_type=ProjectType.objects.get(code='INDEPENDENT'))

        with self.assertRaises(ValidationError):
            CapstoneProject.objects.create(project=project, term=self.term)

    def test_capstone_project_rejects_project_without_advisor(self):
        project = self.create_project(advisor=False)

        with self.assertRaises(ValidationError):
            CapstoneProject.objects.create(project=project, term=self.term)

    def test_capstone_project_is_unique_per_project(self):
        project = self.create_project()
        CapstoneProject.objects.create(project=project, term=self.term)

        with self.assertRaises(ValidationError):
            CapstoneProject.objects.create(project=project, term=self.term)

    def test_checkpoint_kind_is_unique_per_capstone_project(self):
        capstone_project = CapstoneProject.objects.create(project=self.create_project(), term=self.term)
        due_at = self.term.midterm_at
        CapstoneCheckpoint.objects.create(
            capstone_project=capstone_project,
            kind=CapstoneCheckpoint.Kind.MIDTERM_REVIEW,
            due_at=due_at,
        )

        with self.assertRaises(ValidationError):
            CapstoneCheckpoint.objects.create(
                capstone_project=capstone_project,
                kind=CapstoneCheckpoint.Kind.MIDTERM_REVIEW,
                due_at=due_at + timedelta(days=1),
            )

    def test_capstone_term_rejects_non_chronological_dates(self):
        starts_at = timezone.now()

        with self.assertRaises(ValidationError):
            CapstoneTerm.objects.create(
                academic_year='2027-2028',
                semester=CapstoneTerm.Semester.SPRING,
                starts_at=starts_at,
                midterm_at=starts_at - timedelta(days=1),
                final_at=starts_at + timedelta(days=60),
            )
