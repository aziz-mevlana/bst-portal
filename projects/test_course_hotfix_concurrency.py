"""Real PostgreSQL row-lock tests, including writes already waiting at lifecycle commit."""
from queue import Queue
from threading import Thread
from time import monotonic, sleep
from unittest import skipUnless

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection, connections, transaction
from django.test import Client, TransactionTestCase
from django.urls import reverse

from core.models import AuditLog, Notification
from . import test_course_workflow_concurrency as fixtures
from .course_work_models import CourseProjectAssignment, CourseProjectParticipation
from .course_work_services import (cancel_assignment, reactivate_assignment, purge_assignment, create_team,
                                  join_team, join_assignment, create_work, save_checkpoint, delete_empty_assignment)
from .milestone_services import submit_milestone, review_milestone
from .models import ProjectMilestoneSubmission, Project


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row locks required.')
class CourseHotfixConcurrencyTests(TransactionTestCase):
    def setUp(self):
        fixtures.CourseWorkflowConcurrencyTests.setUp(self)
        self.admin = User.objects.create_user('hotfix-race-admin', is_staff=True)

    def work(self):
        team = create_team(assignment=self.assignment, student=self.students[0], name='Takım')
        join_team(assignment=self.assignment, student=self.students[1], team_id=team.pk)
        save_checkpoint(assignment=self.assignment, actor=self.teacher,
            values=dict(title='Analiz', description='', order=1, due_at=self.assignment.ends_at, is_active=True))
        work = create_work(assignment=self.assignment, student=self.students[0], title='Proje', idea='Fikir')
        return work, work.project.milestones.get()

    def blocked_write(self, lifecycle, mutation, expected='rejected'):
        """Prove mutation has reached a PostgreSQL lock wait before committing lifecycle."""
        ready, output = Queue(), Queue()
        def worker():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '12s'")
                    cursor.execute('SELECT pg_backend_pid()')
                    ready.put(cursor.fetchone()[0])
                result = mutation()
                status = getattr(result, 'status_code', None)
                if status is not None:
                    if status not in (200, 302, 403, 404):
                        raise AssertionError(f'Unexpected HTTP status: {status}')
                output.put('rejected' if status in (403, 404) else 'accepted')
            except (ValidationError, PermissionDenied, CourseProjectAssignment.DoesNotExist):
                output.put('rejected')
            except Exception as exc:
                output.put(exc)
            finally:
                connections.close_all()
        thread = Thread(target=worker)
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_backend_pid()')
            main_pid = cursor.fetchone()[0]
        with transaction.atomic():
            CourseProjectAssignment.objects.select_for_update().get(pk=self.assignment.pk)
            thread.start()
            pid = ready.get(timeout=10)
            self.assertNotEqual(pid, main_pid)
            deadline = monotonic()+10
            while monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_stat_clear_snapshot()')
                    cursor.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s', [pid])
                    row = cursor.fetchone()
                if row and row[0] == 'Lock':
                    break
                sleep(0.02)
            else:
                self.fail('Mutation did not wait on the assignment lock.')
            lifecycle()
        thread.join(timeout=15)
        self.assertFalse(thread.is_alive(), 'Possible deadlock')
        self.assertEqual(output.get(timeout=1), expected)

    def cancel(self):
        cancel_assignment(assignment=self.assignment, actor=self.teacher, reason='İptal')

    def purge(self):
        purge_assignment(assignment=self.assignment, actor=self.admin, reason='Kalıcı sil')

    def test_cancel_commit_blocks_waiting_submission(self):
        work, milestone = self.work()
        self.blocked_write(self.cancel, lambda: submit_milestone(milestone=milestone, actor=self.students[0]))
        self.assertFalse(ProjectMilestoneSubmission.objects.filter(milestone=milestone).exists())

    def test_cancel_commit_blocks_waiting_invite_join(self):
        CourseProjectParticipation.objects.filter(assignment=self.assignment, student=self.students[2]).delete()
        self.blocked_write(self.cancel, lambda: join_assignment(token=self.assignment.invitation_token, student=self.students[2]))
        self.assertFalse(CourseProjectParticipation.objects.filter(assignment=self.assignment, student=self.students[2]).exists())

    def test_cancel_commit_blocks_waiting_team_join(self):
        team = create_team(assignment=self.assignment, student=self.students[0], name='Takım')
        self.blocked_write(self.cancel, lambda: join_team(assignment=self.assignment, student=self.students[1], team_id=team.pk))
        self.assertEqual(team.participants.count(), 1)

    def test_purge_commit_blocks_waiting_submission(self):
        work, milestone = self.work()
        self.blocked_write(self.purge, lambda: submit_milestone(milestone=milestone, actor=self.students[0]))
        self.assertFalse(Project.objects.filter(pk=work.project_id).exists())
        self.assertFalse(ProjectMilestoneSubmission.objects.filter(milestone_id=milestone.pk).exists())
        self.assertEqual(AuditLog.objects.filter(action='course.assignment_purged').count(), 1)

    def test_purge_commit_blocks_waiting_team_mutation(self):
        self.blocked_write(self.purge, lambda: create_team(assignment=self.assignment, student=self.students[0], name='Yeni'))
        self.assertFalse(CourseProjectAssignment.objects.filter(pk=self.assignment.pk).exists())
        self.assertFalse(CourseProjectParticipation.objects.filter(assignment_id=self.assignment.pk).exists())

    def test_reactivate_commit_rejects_old_duplicate_cancel(self):
        self.cancel()
        self.assignment.refresh_from_db()
        old_version = 0
        self.blocked_write(
            lambda: reactivate_assignment(assignment=self.assignment, actor=self.admin, reason='Yeniden aç'),
            lambda: cancel_assignment(assignment=self.assignment, actor=self.teacher, reason='Eski form', expected_version=old_version))
        self.assignment.refresh_from_db()
        self.assertTrue(self.assignment.is_active)
        self.assertEqual(AuditLog.objects.filter(action='course.assignment_cancelled').count(), 1)
        self.assertEqual(AuditLog.objects.filter(action='course.assignment_reactivated').count(), 1)
        self.assertEqual(Notification.objects.filter(dedupe_key__startswith='course-assignment-cancelled-').count(), 3)

    def test_duplicate_cancels_serialize_without_duplicate_notices(self):
        results = fixtures.CourseWorkflowConcurrencyTests.race(self, self.cancel, self.cancel)
        self.assertEqual([state for state, _ in results], ['ok', 'ok'])
        self.assertEqual(AuditLog.objects.filter(action='course.assignment_cancelled').count(), 1)
        self.assertEqual(Notification.objects.filter(dedupe_key__startswith='course-assignment-cancelled-').count(), 3)

    def test_cancel_commit_blocks_waiting_work_initialization(self):
        team = create_team(assignment=self.assignment, student=self.students[0], name='Takım')
        join_team(assignment=self.assignment, student=self.students[1], team_id=team.pk)
        self.blocked_write(self.cancel, lambda: create_work(assignment=self.assignment,
            student=self.students[0], title='Yeni proje', idea='Fikir'))
        self.assertFalse(self.assignment.works.exists())
        self.assertFalse(Project.objects.filter(course=self.course, creation_source='COURSE_ASSIGNMENT').exists())

    def test_purge_commit_blocks_waiting_team_join(self):
        team = create_team(assignment=self.assignment, student=self.students[0], name='Takım')
        self.blocked_write(self.purge, lambda: join_team(assignment=self.assignment,
            student=self.students[1], team_id=team.pk))
        self.assertFalse(CourseProjectParticipation.objects.filter(assignment_id=self.assignment.pk).exists())
        self.assertFalse(self.assignment.teams.exists())

    def test_purge_commit_blocks_repository_route(self):
        work, _ = self.work()
        def repository_post():
            client = Client()
            client.force_login(self.students[0])
            return client.post(reverse('projects:project_repository_save', args=[work.project_id]),
                               {'repository_path': 'bst/race'})
        self.blocked_write(self.purge, repository_post)
        self.assertFalse(Project.objects.filter(pk=work.project_id).exists())

    def test_purge_commit_blocks_waiting_review(self):
        work, milestone = self.work()
        submission = submit_milestone(milestone=milestone, actor=self.students[0])
        self.blocked_write(self.purge, lambda: review_milestone(submission=submission,
            actor=self.teacher, outcome='APPROVED'))
        self.assertFalse(ProjectMilestoneSubmission.objects.filter(pk=submission.pk).exists())

    def test_purge_commit_cancel_route_returns_404(self):
        def cancel_post():
            client = Client()
            client.force_login(self.teacher)
            return client.post(reverse('projects:course_assignment_action', args=[self.assignment.pk, 'cancel']),
                               {'confirm': 'yes', 'version': 0, 'reason': 'İptal'})
        self.blocked_write(self.purge, cancel_post)
        self.assertFalse(AuditLog.objects.filter(action='course.assignment_cancelled').exists())
        self.assertFalse(Notification.objects.filter(dedupe_key__startswith='course-assignment-cancelled-').exists())

    def test_teacher_delete_commit_blocks_waiting_invite_join(self):
        CourseProjectParticipation.objects.filter(assignment=self.assignment).delete()
        self.blocked_write(
            lambda: delete_empty_assignment(assignment=self.assignment, actor=self.teacher, reason='Boş çalışma'),
            lambda: join_assignment(token=self.assignment.invitation_token, student=self.students[0]))
        self.assertFalse(CourseProjectParticipation.objects.filter(assignment_id=self.assignment.pk).exists())

    def test_submission_winning_race_is_preserved_by_cancel(self):
        work, milestone = self.work()
        self.blocked_write(lambda: submit_milestone(milestone=milestone, actor=self.students[0]),
                           self.cancel, expected='accepted')
        self.assignment.refresh_from_db()
        self.assertTrue(self.assignment.is_cancelled)
        self.assertEqual(ProjectMilestoneSubmission.objects.filter(milestone=milestone).count(), 1)

    def test_submission_winning_race_is_deleted_by_purge(self):
        work, milestone = self.work()
        self.blocked_write(lambda: submit_milestone(milestone=milestone, actor=self.students[0]),
                           self.purge, expected='accepted')
        self.assertFalse(Project.objects.filter(pk=work.project_id).exists())
        self.assertFalse(ProjectMilestoneSubmission.objects.filter(milestone_id=milestone.pk).exists())
