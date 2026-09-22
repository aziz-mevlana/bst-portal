from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import AuditLog
from projects.models import Project, ProjectType

from .models import CapstoneEnrollment, CapstoneProject, CapstoneTerm
from .services import create_capstone_project


class CapstoneProjectCreationServiceTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.term = CapstoneTerm.objects.create(
            academic_year='2026-2027',
            semester=CapstoneTerm.Semester.FALL,
            starts_at=now,
            midterm_at=now + timedelta(weeks=8),
            final_at=now + timedelta(weeks=16),
            is_active=True,
        )
        self.capstone_type = ProjectType.objects.get(code='CAPSTONE')
        self.student = self.create_user('capstone-service-student', class_level='4')
        self.advisor = self.create_user('capstone-service-advisor', user_type='teacher')
        self.enrollment = CapstoneEnrollment.objects.create(term=self.term, student=self.student)

    def create_user(self, username, *, user_type='student', class_level='1', **user_fields):
        user = User.objects.create_user(username, password='StrongPassword123!', **user_fields)
        user.profile.user_type = user_type
        user.profile.class_level = class_level if user_type in {'student', 'staff_student'} else None
        user.profile.save(update_fields=['user_type', 'class_level'])
        return user

    def create_capstone(self, **overrides):
        values = {
            'student': self.student,
            'advisor': self.advisor,
            'title': 'Güvenli Bitirme Projesi',
            'description': 'Merkezi servis ile oluşturuldu.',
            'term': self.term,
        }
        values.update(overrides)
        return create_capstone_project(**values)

    def test_eligible_student_creates_complete_capstone_aggregate(self):
        capstone_project = self.create_capstone()
        project = capstone_project.project

        self.assertEqual(project.project_type.code, 'CAPSTONE')
        self.assertEqual(project.visibility, 'private')
        self.assertTrue(project.is_private)
        self.assertEqual(project.created_by, self.student)
        self.assertEqual(project.advisor, self.advisor)
        self.assertTrue(project.team.filter(pk=self.student.pk).exists())
        self.assertEqual(capstone_project.term, self.term)
        self.assertEqual(capstone_project.checkpoints.count(), 4)
        self.assertEqual(project.status, 'in_review')
        self.assertEqual(project.approval_status, 'pending')
        self.assertEqual(project.development_status, 'idea')
        self.assertTrue(AuditLog.objects.filter(
            actor=self.student,
            action='capstone.project_created',
            target_type='projects.project',
            target_id=str(project.pk),
        ).exists())

    def test_student_without_enrollment_is_rejected(self):
        student = self.create_user('unenrolled-service-student', class_level='4')

        with self.assertRaises(ValidationError):
            self.create_capstone(student=student)

    def test_student_who_is_no_longer_fourth_year_is_rejected(self):
        self.student.profile.class_level = '3'
        self.student.profile.save(update_fields=['class_level'])

        with self.assertRaises(ValidationError):
            self.create_capstone()

    def test_inactive_enrollment_is_rejected(self):
        self.enrollment.is_active = False
        self.enrollment.save(update_fields=['is_active', 'updated_at'])

        with self.assertRaises(ValidationError):
            self.create_capstone()

    def test_missing_active_term_is_rejected_when_term_is_omitted(self):
        self.term.is_active = False
        self.term.save(update_fields=['is_active', 'updated_at'])

        with self.assertRaises(ValidationError):
            self.create_capstone(term=None)

    def test_explicit_inactive_term_is_rejected(self):
        self.term.is_active = False
        self.term.save(update_fields=['is_active', 'updated_at'])

        with self.assertRaises(ValidationError):
            self.create_capstone(term=self.term)

    def test_missing_advisor_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.create_capstone(advisor=None)

    def test_non_teacher_and_admin_advisors_are_rejected(self):
        invalid_advisors = (
            self.create_user('student-advisor', class_level='4'),
            self.create_user('staff-student-advisor', user_type='staff_student', class_level='4'),
            self.create_user('admin-advisor', is_staff=True),
        )
        for advisor in invalid_advisors:
            with self.subTest(advisor=advisor.username):
                with self.assertRaises(ValidationError):
                    self.create_capstone(advisor=advisor)

    def test_missing_capstone_project_type_is_rejected(self):
        ProjectType.objects.filter(pk=self.capstone_type.pk).update(code='RETIRED_CAPSTONE')

        with self.assertRaises(ValidationError):
            self.create_capstone()

    def test_inactive_capstone_project_type_is_rejected(self):
        self.capstone_type.is_active = False
        self.capstone_type.save(update_fields=['is_active', 'updated_at'])

        with self.assertRaises(ValidationError):
            self.create_capstone()

    def test_same_student_cannot_start_second_project_in_same_term(self):
        first = self.create_capstone()

        with self.assertRaises(ValidationError):
            self.create_capstone(title='İkinci Bitirme Projesi')

        self.assertEqual(
            CapstoneProject.objects.filter(term=self.term, project__created_by=self.student).count(),
            1,
        )
        self.assertEqual(Project.objects.filter(pk=first.project_id).count(), 1)

    def test_checkpoint_failure_rolls_back_entire_project(self):
        with patch(
            'capstone.services.create_capstone_checkpoints',
            side_effect=ValidationError('Checkpoint oluşturulamadı.'),
        ):
            with self.assertRaises(ValidationError):
                self.create_capstone()

        self.assertFalse(Project.objects.filter(created_by=self.student).exists())
        self.assertFalse(CapstoneProject.objects.exists())
        self.assertFalse(AuditLog.objects.filter(action='capstone.project_created').exists())
