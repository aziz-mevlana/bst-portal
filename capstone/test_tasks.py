from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from projects.models import Project, ProjectType

from .models import CapstoneCheckpoint, CapstoneProject, CapstoneTask, CapstoneTerm


class CapstoneTaskModelTests(TestCase):
    def setUp(self):
        self.owner = self.create_user('task-owner', 'student')
        self.advisor = self.create_user('task-advisor', 'teacher')
        self.unrelated_teacher = self.create_user('task-other-teacher', 'teacher')
        now = timezone.now()
        self.term = CapstoneTerm.objects.create(
            academic_year='2026-2027',
            semester=CapstoneTerm.Semester.FALL,
            starts_at=now,
            midterm_at=now + timedelta(weeks=8),
            final_at=now + timedelta(weeks=16),
            is_active=True,
        )
        self.capstone_project, self.checkpoint = self.create_capstone(
            title='Görev testi projesi',
            owner=self.owner,
            advisor=self.advisor,
            checkpoint_kind=CapstoneCheckpoint.Kind.FIRST_REVIEW,
        )
        other_owner = self.create_user('task-other-owner', 'student')
        other_advisor = self.create_user('task-other-advisor', 'teacher')
        self.other_capstone_project, self.other_checkpoint = self.create_capstone(
            title='Başka bitirme projesi',
            owner=other_owner,
            advisor=other_advisor,
            checkpoint_kind=CapstoneCheckpoint.Kind.MIDTERM_REVIEW,
        )

    def create_user(self, username, user_type='student', **user_fields):
        user = User.objects.create_user(username, password='StrongPassword123!', **user_fields)
        user.profile.user_type = user_type
        user.profile.class_level = '4' if user_type in {'student', 'staff_student'} else None
        user.profile.save(update_fields=['user_type', 'class_level'])
        return user

    def create_capstone(self, *, title, owner, advisor, checkpoint_kind):
        project = Project.objects.create(
            project_type=ProjectType.objects.get(code='CAPSTONE'),
            title=title,
            created_by=owner,
            advisor=advisor,
        )
        capstone_project = CapstoneProject.objects.create(project=project, term=self.term)
        checkpoint = CapstoneCheckpoint.objects.create(
            capstone_project=capstone_project,
            kind=checkpoint_kind,
            due_at=self.term.midterm_at,
        )
        return capstone_project, checkpoint

    def task_values(self, **overrides):
        values = {
            'capstone_project': self.capstone_project,
            'checkpoint': self.checkpoint,
            'created_by': self.advisor,
            'title': 'Literatür taraması',
            'instructions': 'Kaynakları inceleyip kısa bir değerlendirme hazırlayın.',
            'required_file_count': 1,
            'due_at': self.checkpoint.due_at,
        }
        values.update(overrides)
        return values

    def test_assigned_advisor_can_create_task(self):
        task = CapstoneTask.objects.create(**self.task_values())

        self.assertEqual(task.created_by, self.advisor)

    def test_django_staff_and_superuser_can_create_task(self):
        admins = (
            self.create_user('task-staff', is_staff=True),
            self.create_user('task-superuser', is_superuser=True),
        )
        for index, admin in enumerate(admins):
            with self.subTest(admin=admin.username):
                task = CapstoneTask.objects.create(
                    **self.task_values(created_by=admin, title=f'Yönetici görevi {index}')
                )
                self.assertEqual(task.created_by, admin)

    def test_owner_student_cannot_create_task(self):
        with self.assertRaises(ValidationError):
            CapstoneTask.objects.create(**self.task_values(created_by=self.owner))

    def test_unrelated_teacher_cannot_create_task(self):
        with self.assertRaises(ValidationError):
            CapstoneTask.objects.create(**self.task_values(created_by=self.unrelated_teacher))

    def test_checkpoint_from_another_capstone_is_rejected(self):
        with self.assertRaises(ValidationError):
            CapstoneTask.objects.create(**self.task_values(checkpoint=self.other_checkpoint))

    def test_zero_required_file_count_is_rejected(self):
        with self.assertRaises(ValidationError):
            CapstoneTask.objects.create(**self.task_values(required_file_count=0))

    def test_required_file_count_above_limit_is_rejected(self):
        with self.assertRaises(ValidationError):
            CapstoneTask.objects.create(**self.task_values(required_file_count=21))

    def test_due_at_after_checkpoint_is_rejected(self):
        with self.assertRaises(ValidationError):
            CapstoneTask.objects.create(
                **self.task_values(due_at=self.checkpoint.due_at + timedelta(seconds=1))
            )

    def test_valid_task_fields_are_saved(self):
        due_at = self.checkpoint.due_at - timedelta(days=1)

        task = CapstoneTask.objects.create(
            **self.task_values(required_file_count=3, due_at=due_at)
        )

        self.assertEqual(task.title, 'Literatür taraması')
        self.assertTrue(task.instructions)
        self.assertEqual(task.required_file_count, 3)
        self.assertEqual(task.due_at, due_at)

    def test_direct_save_cannot_bypass_model_invariants(self):
        task = CapstoneTask(**self.task_values(checkpoint=self.other_checkpoint))

        with self.assertRaises(ValidationError):
            task.save()

        self.assertIsNone(task.pk)
