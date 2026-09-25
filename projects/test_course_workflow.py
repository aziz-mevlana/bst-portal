from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from core.models import AuditLog, Notification

from .course_work_models import (CourseAssignmentCheckpoint, CourseProjectAssignment,
    CourseProjectParticipation, CourseProjectWork)
from .course_work_services import (create_assignment, create_team, create_work, join_assignment,
    join_team, override_team_member, rotate_invitation, save_checkpoint)
from .milestone_services import review_milestone, submit_milestone
from .models import Course, CourseInstructor, Project, ProjectType


def user(name, role):
    account = User.objects.create_user(name, password='test-password')
    account.profile.user_type = role
    account.profile.class_level = '2' if role == 'student' else None
    account.profile.save()
    return account


class CourseAssignmentWorkflowTests(TestCase):
    def setUp(self):
        self.teacher = user('assignment-teacher', 'teacher')
        self.other_teacher = user('other-assignment-teacher', 'teacher')
        self.student = user('assignment-student', 'student')
        self.second_student = user('second-assignment-student', 'student')
        self.third_student = user('third-assignment-student', 'student')
        self.course = Course.objects.get(code='BST 207')
        CourseInstructor.objects.create(course=self.course, instructor=self.teacher)
        self.now = timezone.now()
        self.values = dict(topic='Python uygulaması', purpose='', expectations='',
            mode='INDIVIDUAL', min_team_size=None, max_team_size=None,
            join_deadline=self.now + timedelta(days=2), starts_at=self.now + timedelta(days=3),
            ends_at=self.now + timedelta(days=30), repository_required=False)

    def assignment(self, **overrides):
        return create_assignment(instructor=self.teacher, course=self.course,
            **{**self.values, **overrides})

    def test_brief_without_project_name_topic_or_purpose_and_permissions(self):
        assignment = self.assignment()
        self.assertEqual(assignment.topic, 'Python uygulaması')
        self.assignment(topic='', purpose='Özgün çözüm geliştir')
        with self.assertRaises(ValidationError):
            self.assignment(topic='', purpose='', expectations='')
        with self.assertRaises(PermissionDenied):
            create_assignment(instructor=self.other_teacher, course=self.course, **self.values)
        with self.assertRaises(ValidationError):
            self.assignment(mode='GROUP', min_team_size=1, max_team_size=3)
        with self.assertRaises(ValidationError):
            self.assignment(join_deadline=self.now + timedelta(days=4))
        with self.assertRaises(ValidationError):
            self.assignment(join_deadline=self.values['join_deadline'].replace(tzinfo=None))

    def test_capstone_courses_cannot_be_assignments(self):
        capstone_course = Course.objects.get(code='BST 401')
        CourseInstructor.objects.create(course=capstone_course, instructor=self.teacher)
        with self.assertRaises(ValidationError):
            create_assignment(instructor=self.teacher, course=capstone_course, **self.values)

    def test_inactive_course_or_removed_instructor_cannot_accept_new_students(self):
        assignment = self.assignment()
        CourseInstructor.objects.filter(course=self.course, instructor=self.teacher).update(is_active=False)
        with self.assertRaises(ValidationError):
            join_assignment(token=assignment.invitation_token, student=self.student)
        CourseInstructor.objects.filter(course=self.course, instructor=self.teacher).update(is_active=True)
        self.course.is_active = False
        self.course.save(update_fields=['is_active'])
        with self.assertRaises(ValidationError):
            self.assignment()

    def test_invitation_is_random_idempotent_and_rotates(self):
        assignment = self.assignment()
        self.assertGreaterEqual(len(assignment.invitation_token), 32)
        join_assignment(token=assignment.invitation_token, student=self.student)
        join_assignment(token=assignment.invitation_token, student=self.student)
        self.assertEqual(assignment.participants.count(), 1)
        previous = assignment.invitation_token
        rotate_invitation(assignment=assignment, actor=self.teacher)
        assignment.refresh_from_db()
        self.assertNotEqual(previous, assignment.invitation_token)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('projects:course_invitation', args=[previous])).status_code, 404)
        assignment.join_deadline = self.now - timedelta(minutes=1)
        assignment.save()
        with self.assertRaises(ValidationError):
            join_assignment(token=assignment.invitation_token, student=self.second_student)

    def test_anonymous_invite_returns_to_same_token_after_login(self):
        assignment = self.assignment()
        url = reverse('projects:course_invitation', args=[assignment.invitation_token])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(f'next={url}', response['Location'])

    def test_join_deadline_includes_exact_instant_but_excludes_later(self):
        assignment = self.assignment()
        with patch('projects.course_work_services.timezone.now', return_value=assignment.join_deadline):
            join_assignment(token=assignment.invitation_token, student=self.student)
        with patch('projects.course_work_services.timezone.now', return_value=assignment.join_deadline + timedelta(microseconds=1)):
            with self.assertRaises(ValidationError):
                join_assignment(token=assignment.invitation_token, student=self.second_student)

    def test_individual_project_and_shared_checkpoint_history(self):
        assignment = self.assignment()
        checkpoint = save_checkpoint(assignment=assignment, actor=self.teacher,
            values=dict(title='Analiz', description='Rapor', order=1, due_at=self.now + timedelta(days=10), is_active=True))
        join_assignment(token=assignment.invitation_token, student=self.student)
        work = create_work(assignment=assignment, student=self.student, title='Projem', idea='Çözüm')
        self.assertEqual(work.project.course_id, self.course.pk)
        self.assertEqual(work.project.visibility, 'private')
        self.assertEqual(work.project.milestones.count(), 1)
        milestone = work.project.milestones.get()
        self.assertEqual(milestone.title, '')
        self.assertEqual(milestone.effective_title, 'Analiz')
        with self.assertRaises(ValidationError):
            create_work(assignment=assignment, student=self.student, title='İkinci', idea='Çözüm')
        submission = submit_milestone(milestone=milestone, actor=self.student, note='Rapor')
        review_milestone(submission=submission, actor=self.teacher, outcome='REVISION_REQUIRED', feedback='Düzelt')
        second = submit_milestone(milestone=milestone, actor=self.student, note='Düzeltildi')
        review_milestone(submission=second, actor=self.teacher, outcome='APPROVED', feedback='Uygun')
        self.assertEqual(milestone.state, 'APPROVED')
        changed = self.now + timedelta(days=15)
        save_checkpoint(assignment=assignment, actor=self.teacher, checkpoint=checkpoint,
            values=dict(title='Analiz', description='Rapor', order=1, due_at=changed, is_active=True))
        milestone.refresh_from_db()
        self.assertEqual(milestone.effective_due_at, changed)
        self.assertEqual(milestone.due_at, None)
        self.assertEqual(checkpoint.project_progress.count(), 1)

    def test_group_team_capacity_and_one_work(self):
        assignment = self.assignment(mode='GROUP', min_team_size=2, max_team_size=2)
        for student in (self.student, self.second_student, self.third_student):
            join_assignment(token=assignment.invitation_token, student=student)
        team = create_team(assignment=assignment, student=self.student, name='Takım A')
        join_team(assignment=assignment, student=self.second_student, team_id=team.pk)
        with self.assertRaises(ValidationError):
            join_team(assignment=assignment, student=self.third_student, team_id=team.pk)
        work = create_work(assignment=assignment, student=self.student, title='Grup Projesi', idea='Bir çözüm')
        self.assertEqual(CourseProjectWork.objects.filter(team=team).count(), 1)
        self.assertEqual(set(work.project.team.values_list('pk', flat=True)), {self.student.pk, self.second_student.pk})
        with self.assertRaises(ValidationError):
            create_work(assignment=assignment, student=self.student, title='İkinci', idea='Çözüm')
        with self.assertRaises(ValidationError):
            override_team_member(assignment=assignment, actor=self.teacher,
                student_id=self.second_student.pk, team_id=None, reason='Düzeltme')
        self.assertEqual(team.participants.count(), 2)

    def test_instructor_can_correct_team_membership_after_join_deadline(self):
        assignment = self.assignment(mode='GROUP', min_team_size=2, max_team_size=2)
        for student in (self.student, self.second_student, self.third_student):
            join_assignment(token=assignment.invitation_token, student=student)
        team = create_team(assignment=assignment, student=self.student, name='Takım A')
        assignment.join_deadline = self.now - timedelta(minutes=1)
        assignment.save()
        with self.assertRaises(ValidationError):
            join_team(assignment=assignment, student=self.second_student, team_id=team.pk)
        with self.assertRaises(PermissionDenied):
            override_team_member(assignment=assignment, actor=self.other_teacher,
                student_id=self.second_student.pk, team_id=team.pk, reason='Düzeltme')
        override_team_member(assignment=assignment, actor=self.teacher,
            student_id=self.second_student.pk, team_id=team.pk, reason='Öğrenci talebi')
        self.assertEqual(CourseProjectParticipation.objects.get(
            assignment=assignment, student=self.second_student).team_id, team.pk)
        self.assertEqual(AuditLog.objects.filter(action='course.team_membership_overridden').count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=self.second_student,
            message__contains='takım üyeliğiniz').count(), 1)
        with self.assertRaises(ValidationError):
            override_team_member(assignment=assignment, actor=self.teacher,
                student_id=self.third_student.pk, team_id=team.pk, reason='Kapasite sınırı')
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.post(reverse('projects:course_team_override',
            args=[assignment.pk, self.second_student.pk]), {'team_id': '', 'reason': 'Test'}).status_code, 404)

    def test_historical_course_project_remains_available(self):
        project_type = ProjectType.objects.get(code='COURSE')
        project = Project.objects.create(project_type=project_type, course=self.course,
            created_by=self.student, title='Geçmiş Ders Projesi')
        self.assertFalse(CourseProjectWork.objects.filter(project=project).exists())

    def test_student_and_teacher_endpoints_enforce_assignment_scope(self):
        assignment = self.assignment()
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(reverse('projects:course_assignment_detail', args=[assignment.pk])),
                            'Katılım Bağlantısı')
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.get(reverse('projects:course_assignment_detail', args=[assignment.pk])).status_code, 404)
        self.client.force_login(self.student)
        invite = reverse('projects:course_invitation', args=[assignment.invitation_token])
        self.assertContains(self.client.get(invite), self.course.name)
        self.assertEqual(self.client.post(reverse('projects:course_work_create', args=[assignment.pk]),
            {'title': 'Sahte', 'idea': 'Fikir'}).status_code, 404)
        self.client.post(invite)
        self.client.post(reverse('projects:course_work_create', args=[assignment.pk]),
            {'title': 'Gerçek proje', 'idea': 'Fikir'})
        work = CourseProjectWork.objects.get(assignment=assignment)
        self.assertContains(self.client.get(reverse('projects:course_work_detail', args=[work.pk])), 'Gerçek proje')
        self.assertContains(self.client.get(reverse('projects:course_my_assignments')),
                            'Çalışma Alanına Git')
        CourseInstructor.objects.create(course=self.course, instructor=self.other_teacher)
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.get(reverse('projects:project_detail', args=[work.project_id])).status_code, 404)
        self.client.force_login(self.second_student)
        self.assertEqual(self.client.get(reverse('projects:course_work_detail', args=[work.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('projects:project_update', args=[work.project_id])).status_code, 404)
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(reverse('projects:project_delete', args=[work.project_id]),
            {'confirm_delete': 'yes'}).status_code, 404)
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(reverse('projects:course_work_detail', args=[work.pk])),
                            'dashboard-shell')

    def test_new_definition_is_shared_across_existing_and_future_works(self):
        assignment = self.assignment()
        for student in (self.student, self.second_student):
            join_assignment(token=assignment.invitation_token, student=student)
        first = create_work(assignment=assignment, student=self.student, title='Bir', idea='Fikir')
        definition = save_checkpoint(assignment=assignment, actor=self.teacher,
            values=dict(title='Analiz', description='', order=1, due_at=self.now + timedelta(days=5), is_active=True))
        second = create_work(assignment=assignment, student=self.second_student, title='İki', idea='Fikir')
        self.assertEqual(CourseAssignmentCheckpoint.objects.filter(assignment=assignment).count(), 1)
        self.assertEqual(definition.project_progress.count(), 2)
        self.assertEqual(first.project.milestones.get().assignment_checkpoint_id, definition.pk)
        self.assertEqual(second.project.milestones.get().assignment_checkpoint_id, definition.pk)
