from datetime import timedelta
from queue import Queue
from threading import Barrier, Thread
from unittest import skipUnless

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from django.utils import timezone

from .course_work_models import CourseProjectParticipation, CourseProjectWork
from .course_work_services import create_assignment, create_team, create_work, join_assignment, join_team, save_checkpoint
from .models import Course, CourseInstructor, Project, ProjectType


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row locks required.')
class CourseWorkflowConcurrencyTests(TransactionTestCase):
    def setUp(self):
        def make_user(name, role):
            user = User.objects.create_user(name, password='password')
            user.profile.user_type = role
            user.profile.class_level = '2' if role == 'student' else None
            user.profile.save()
            return user
        self.teacher = make_user('course-race-teacher', 'teacher')
        self.students = [make_user(f'course-race-student-{i}', 'student') for i in range(3)]
        self.course, _ = Course.objects.get_or_create(code='BST 207', defaults={'name': 'Python Programlama'})
        ProjectType.objects.get_or_create(code='COURSE', defaults={
            'name': 'Ders Projesi', 'slug': 'ders-projesi', 'requires_course': True})
        CourseInstructor.objects.create(course=self.course, instructor=self.teacher)
        now = timezone.now()
        self.assignment = create_assignment(instructor=self.teacher, course=self.course,
            topic='Yarış testi', purpose='', expectations='', mode='GROUP',
            min_team_size=2, max_team_size=2, join_deadline=now + timedelta(days=2),
            starts_at=now + timedelta(days=3), ends_at=now + timedelta(days=20),
            repository_required=False)
        for student in self.students:
            join_assignment(token=self.assignment.invitation_token, student=student)

    def race(self, left, right):
        barrier, output = Barrier(2), Queue()
        def worker(operation):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                output.put(('ok', operation()))
            except (ValidationError, PermissionDenied):
                output.put(('rejected', None))
            except Exception as exc:
                output.put((type(exc).__name__, str(exc)))
            finally:
                connections.close_all()
        threads = [Thread(target=worker, args=(operation,)) for operation in (left, right)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
            self.assertFalse(thread.is_alive())
        return [output.get_nowait() for _ in threads]

    def test_last_team_seat_cannot_be_overbooked(self):
        team = create_team(assignment=self.assignment, student=self.students[0], name='Tek takım')
        results = self.race(
            lambda: join_team(assignment=self.assignment, student=self.students[1], team_id=team.pk).pk,
            lambda: join_team(assignment=self.assignment, student=self.students[2], team_id=team.pk).pk)
        self.assertEqual([state for state, _ in results].count('ok'), 1)
        self.assertEqual(CourseProjectParticipation.objects.filter(team=team).count(), 2)

    def test_invitation_double_submit_remains_one_participation(self):
        CourseProjectParticipation.objects.filter(
            assignment=self.assignment, student=self.students[0]).delete()
        results = self.race(
            lambda: join_assignment(token=self.assignment.invitation_token, student=self.students[0]).pk,
            lambda: join_assignment(token=self.assignment.invitation_token, student=self.students[0]).pk)
        self.assertEqual([state for state, _ in results].count('ok'), 2)
        self.assertEqual(CourseProjectParticipation.objects.filter(
            assignment=self.assignment, student=self.students[0]).count(), 1)

    def test_team_project_double_submit_creates_one_project(self):
        team = create_team(assignment=self.assignment, student=self.students[0], name='Tek takım')
        join_team(assignment=self.assignment, student=self.students[1], team_id=team.pk)
        results = self.race(
            lambda: create_work(assignment=self.assignment, student=self.students[0], title='Bir', idea='Fikir').pk,
            lambda: create_work(assignment=self.assignment, student=self.students[0], title='İki', idea='Fikir').pk)
        self.assertEqual([state for state, _ in results].count('ok'), 1)
        self.assertEqual(CourseProjectWork.objects.filter(team=team).count(), 1)
        self.assertEqual(Project.objects.filter(course=self.course, creation_source='COURSE_ASSIGNMENT').count(), 1)

    def test_plan_date_change_and_project_creation_keep_progress_linked(self):
        team = create_team(assignment=self.assignment, student=self.students[0], name='Tek takım')
        join_team(assignment=self.assignment, student=self.students[1], team_id=team.pk)
        due = timezone.now() + timedelta(days=7)
        definition = save_checkpoint(assignment=self.assignment, actor=self.teacher,
            values=dict(title='Analiz', description='', order=1, due_at=due, is_active=True))
        changed = due + timedelta(days=2)
        results = self.race(
            lambda: save_checkpoint(assignment=self.assignment, actor=self.teacher, checkpoint=definition,
                values=dict(title='Analiz', description='', order=1, due_at=changed, is_active=True)).pk,
            lambda: create_work(assignment=self.assignment, student=self.students[0], title='Bir', idea='Fikir').pk)
        self.assertEqual([state for state, _ in results].count('ok'), 2)
        definition.refresh_from_db()
        progress = definition.project_progress.get()
        self.assertEqual(progress.effective_due_at, changed)
