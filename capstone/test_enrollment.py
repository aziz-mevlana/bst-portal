from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from .models import CapstoneEnrollment, CapstoneTerm
from .policies import is_capstone_eligible_student


class CapstoneEnrollmentPolicyTests(TestCase):
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

    def create_user(self, username, *, user_type='student', class_level='4', **user_fields):
        user = User.objects.create_user(username, password='StrongPassword123!', **user_fields)
        user.profile.user_type = user_type
        user.profile.class_level = class_level if user_type in {'student', 'staff_student'} else None
        user.profile.save(update_fields=['user_type', 'class_level'])
        return user

    def enroll(self, user, **overrides):
        values = {'term': self.term, 'student': user}
        values.update(overrides)
        return CapstoneEnrollment.objects.create(**values)

    def test_fourth_year_student_can_be_enrolled(self):
        student = self.create_user('eligible-student')

        enrollment = self.enroll(student)

        self.assertEqual(enrollment.student, student)

    def test_fourth_year_staff_student_can_be_enrolled(self):
        student = self.create_user('eligible-staff-student', user_type='staff_student')

        enrollment = self.enroll(student)

        self.assertEqual(enrollment.student, student)

    def test_lower_class_levels_are_rejected(self):
        for class_level in ('1', '2', '3'):
            with self.subTest(class_level=class_level):
                student = self.create_user(f'class-{class_level}', class_level=class_level)
                with self.assertRaises(ValidationError):
                    self.enroll(student)

    def test_non_student_roles_are_rejected(self):
        for user_type in ('teacher', 'alumni', 'visitor'):
            with self.subTest(user_type=user_type):
                user = self.create_user(f'role-{user_type}', user_type=user_type)
                with self.assertRaises(ValidationError):
                    self.enroll(user)

    def test_duplicate_term_student_enrollment_is_rejected(self):
        student = self.create_user('duplicate-student')
        self.enroll(student)

        with self.assertRaises(ValidationError):
            self.enroll(student)

    def test_normal_teacher_cannot_approve_enrollment(self):
        student = self.create_user('teacher-approved-student')
        teacher = self.create_user('normal-teacher', user_type='teacher')

        with self.assertRaises(ValidationError):
            self.enroll(student, approved_by=teacher)

    def test_staff_or_superuser_can_approve_enrollment(self):
        approvers = (
            self.create_user('staff-approver', is_staff=True),
            self.create_user('superuser-approver', is_superuser=True, is_staff=True),
        )
        for index, approver in enumerate(approvers):
            with self.subTest(approver=approver.username):
                student = self.create_user(f'approved-student-{index}')
                enrollment = self.enroll(student, approved_by=approver)
                self.assertEqual(enrollment.approved_by, approver)

    def test_fourth_year_without_enrollment_is_not_eligible(self):
        student = self.create_user('not-enrolled-student')

        self.assertFalse(is_capstone_eligible_student(student, self.term))

    def test_enrollment_does_not_override_changed_class_level(self):
        student = self.create_user('changed-class-student')
        self.enroll(student)
        student.profile.class_level = '3'
        student.profile.save(update_fields=['class_level'])

        self.assertFalse(is_capstone_eligible_student(student, self.term))

    def test_inactive_enrollment_is_not_eligible(self):
        student = self.create_user('inactive-enrollment-student')
        self.enroll(student, is_active=False)

        self.assertFalse(is_capstone_eligible_student(student, self.term))

    def test_enrollment_for_another_term_is_not_eligible_for_active_term(self):
        student = self.create_user('other-term-student')
        other_term = CapstoneTerm.objects.create(
            academic_year='2027-2028',
            semester=CapstoneTerm.Semester.SPRING,
            starts_at=self.term.final_at + timedelta(days=1),
            midterm_at=self.term.final_at + timedelta(weeks=8),
            final_at=self.term.final_at + timedelta(weeks=16),
        )
        CapstoneEnrollment.objects.create(term=other_term, student=student)

        self.assertFalse(is_capstone_eligible_student(student))

    def test_active_fourth_year_with_active_enrollment_is_eligible(self):
        student = self.create_user('active-enrolled-student')
        self.enroll(student)

        self.assertTrue(is_capstone_eligible_student(student, self.term))

    def test_active_term_is_used_when_term_is_omitted(self):
        student = self.create_user('default-term-student')
        self.enroll(student)

        self.assertTrue(is_capstone_eligible_student(student))

    def test_missing_active_term_returns_false(self):
        student = self.create_user('no-active-term-student')
        self.enroll(student)
        self.term.is_active = False
        self.term.save(update_fields=['is_active', 'updated_at'])

        self.assertFalse(is_capstone_eligible_student(student))
