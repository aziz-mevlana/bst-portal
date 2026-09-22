from datetime import timedelta

from django.contrib.auth.models import AnonymousUser, User
from django.test import TestCase
from django.utils import timezone

from projects.models import Project, ProjectType

from .models import CapstoneEnrollment, CapstoneProject, CapstoneTerm
from .policies import (
    can_administer_capstone,
    can_review_capstone,
    can_submit_capstone,
    can_view_capstone,
)

DEFAULT_CAPSTONE_TARGET = object()


class CapstoneAuthorizationPolicySmokeTests(TestCase):
    def setUp(self):
        self.owner = self.create_user('policy-owner', 'student', class_level='3')
        self.advisor = self.create_user('policy-advisor', 'teacher')
        now = timezone.now()
        self.term = CapstoneTerm.objects.create(
            academic_year='2026-2027',
            semester=CapstoneTerm.Semester.FALL,
            starts_at=now,
            midterm_at=now + timedelta(weeks=8),
            final_at=now + timedelta(weeks=16),
            is_active=True,
        )
        project = Project.objects.create(
            project_type=ProjectType.objects.get(code='CAPSTONE'),
            title='Policy testi bitirme projesi',
            created_by=self.owner,
            advisor=self.advisor,
        )
        self.capstone_project = CapstoneProject.objects.create(project=project, term=self.term)

    def create_user(self, username, user_type='student', *, class_level='4', **user_fields):
        user = User.objects.create_user(username, password='StrongPassword123!', **user_fields)
        user.profile.user_type = user_type
        user.profile.class_level = class_level if user_type in {'student', 'staff_student'} else None
        user.profile.save(update_fields=['user_type', 'class_level'])
        return user

    def assert_permissions(
        self,
        user,
        *,
        view=False,
        submit=False,
        review=False,
        administer=False,
        capstone_project=DEFAULT_CAPSTONE_TARGET,
    ):
        target = self.capstone_project if capstone_project is DEFAULT_CAPSTONE_TARGET else capstone_project
        self.assertEqual(can_view_capstone(user, target), view)
        self.assertEqual(can_submit_capstone(user, target), submit)
        self.assertEqual(can_review_capstone(user, target), review)
        self.assertEqual(can_administer_capstone(user, target), administer)

    def test_owner_student_and_staff_student_permission_matrix(self):
        for role in ('student', 'staff_student'):
            with self.subTest(role=role):
                self.owner.profile.user_type = role
                self.owner.profile.save(update_fields=['user_type'])
                self.assert_permissions(self.owner, view=True, submit=True)

    def test_assigned_active_teacher_advisor_permission_matrix(self):
        self.assert_permissions(self.advisor, view=True, review=True)

    def test_django_staff_and_superuser_permission_matrix(self):
        admins = (
            self.create_user('policy-staff', is_staff=True),
            self.create_user('policy-superuser', is_superuser=True),
        )
        for admin in admins:
            with self.subTest(admin=admin.username):
                self.assert_permissions(admin, view=True, review=True, administer=True)

    def test_unrelated_role_permission_matrix(self):
        unrelated_users = (
            self.create_user('policy-unrelated-teacher', 'teacher'),
            self.create_user('policy-unrelated-student', 'student'),
            self.create_user('policy-unrelated-staff-student', 'staff_student'),
        )
        for user in unrelated_users:
            with self.subTest(role=user.profile.user_type):
                self.assert_permissions(user)

    def test_project_team_membership_does_not_grant_capstone_permissions(self):
        team_member = self.create_user('policy-team-member', 'staff_student')
        self.capstone_project.project.team.add(team_member)

        self.assert_permissions(team_member)

    def test_anonymous_user_permission_matrix(self):
        self.assert_permissions(AnonymousUser())

    def test_inactive_owner_can_view_but_cannot_submit(self):
        self.owner.is_active = False
        self.owner.save(update_fields=['is_active'])

        self.assert_permissions(self.owner, view=True)

    def test_inactive_or_non_teacher_assigned_advisor_cannot_review(self):
        self.advisor.is_active = False
        self.advisor.save(update_fields=['is_active'])
        self.assert_permissions(self.advisor, view=True)

        self.advisor.is_active = True
        self.advisor.save(update_fields=['is_active'])
        self.advisor.profile.user_type = 'student'
        self.advisor.profile.class_level = '4'
        self.advisor.profile.save(update_fields=['user_type', 'class_level'])
        self.assert_permissions(self.advisor, view=True)

    def test_owner_authorization_is_independent_from_class_and_enrollment(self):
        self.assertEqual(self.owner.profile.class_level, '3')
        self.assert_permissions(self.owner, view=True, submit=True)

        self.owner.profile.class_level = '4'
        self.owner.profile.save(update_fields=['class_level'])
        CapstoneEnrollment.objects.create(
            term=self.term,
            student=self.owner,
            is_active=False,
        )
        self.owner.profile.class_level = '2'
        self.owner.profile.save(update_fields=['class_level'])

        self.assert_permissions(self.owner, view=True, submit=True)

    def test_enrollment_in_another_term_does_not_change_project_permissions(self):
        self.owner.profile.class_level = '4'
        self.owner.profile.save(update_fields=['class_level'])
        other_term = CapstoneTerm.objects.create(
            academic_year='2027-2028',
            semester=CapstoneTerm.Semester.SPRING,
            starts_at=self.term.final_at + timedelta(days=1),
            midterm_at=self.term.final_at + timedelta(weeks=8),
            final_at=self.term.final_at + timedelta(weeks=16),
        )
        CapstoneEnrollment.objects.create(term=other_term, student=self.owner)

        self.assert_permissions(self.owner, view=True, submit=True)

    def test_missing_or_broken_relations_return_false(self):
        broken_capstone = CapstoneProject()
        for target in (None, broken_capstone):
            with self.subTest(target=target):
                self.assert_permissions(self.owner, capstone_project=target)
