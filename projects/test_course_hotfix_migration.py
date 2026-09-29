from datetime import timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class CourseLifecycleMigrationTests(TransactionTestCase):
    def test_existing_active_assignments_remain_active_and_history_preserved(self):
        previous = [('projects', '0029_alter_projectmilestone_title')]
        current = [('projects', '0030_courseprojectassignment_cancellation_reason_and_more')]
        executor = MigrationExecutor(connection)
        leaves = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(previous)
            apps = executor.loader.project_state(previous).apps
            User = apps.get_model('auth', 'User')
            Course = apps.get_model('projects', 'Course')
            Assignment = apps.get_model('projects', 'CourseProjectAssignment')
            Participation = apps.get_model('projects', 'CourseProjectParticipation')
            instructor = User.objects.create(username='lifecycle-migration-teacher')
            student = User.objects.create(username='lifecycle-migration-student')
            course, _ = Course.objects.get_or_create(code='BST 207', defaults={'name': 'Python Programlama', 'slug': 'python-migration'})
            now = timezone.now()
            active = Assignment.objects.create(course=course, instructor=instructor, topic='Mevcut çalışma',
                join_deadline=now+timedelta(days=1), starts_at=now+timedelta(days=2), ends_at=now+timedelta(days=5))
            inactive = Assignment.objects.create(course=course, instructor=instructor, topic='Pasif çalışma', is_active=False,
                join_deadline=now+timedelta(days=1), starts_at=now+timedelta(days=2), ends_at=now+timedelta(days=5))
            participation = Participation.objects.create(assignment=active, student=student)
            executor = MigrationExecutor(connection)
            executor.migrate(current)
            apps = executor.loader.project_state(current).apps
            Assignment = apps.get_model('projects', 'CourseProjectAssignment')
            Participation = apps.get_model('projects', 'CourseProjectParticipation')
            self.assertTrue(Assignment.objects.get(pk=active.pk).is_active)
            self.assertFalse(Assignment.objects.get(pk=inactive.pk).is_active)
            for assignment in Assignment.objects.filter(pk__in=[active.pk, inactive.pk]):
                self.assertIsNone(assignment.cancelled_at)
                self.assertIsNone(assignment.cancelled_by_id)
                self.assertEqual(assignment.cancellation_reason, '')
                self.assertEqual(assignment.lifecycle_version, 0)
            self.assertTrue(Participation.objects.filter(pk=participation.pk, student_id=student.pk).exists())
            # Reverse removes only newly added metadata; aggregate/history and active flag survive.
            from core.models import AuditLog
            Assignment.objects.filter(pk=inactive.pk).update(cancelled_at=now, cancelled_by_id=instructor.pk,
                cancellation_reason='Prova iptali', lifecycle_version=1)
            audit = AuditLog.objects.create(actor_id=instructor.pk, action='course.assignment_cancelled',
                target_type='projects.courseprojectassignment', target_id=str(inactive.pk),
                metadata={'reason': 'Prova iptali', 'assignment_id': inactive.pk})
            executor = MigrationExecutor(connection)
            executor.migrate(previous)
            old_apps = executor.loader.project_state(previous).apps
            OldAssignment = old_apps.get_model('projects', 'CourseProjectAssignment')
            self.assertTrue(OldAssignment.objects.get(pk=active.pk).is_active)
            self.assertFalse(OldAssignment.objects.get(pk=inactive.pk).is_active)
            self.assertEqual(OldAssignment.objects.get(pk=active.pk).topic, 'Mevcut çalışma')
            self.assertTrue(old_apps.get_model('projects', 'CourseProjectParticipation').objects.filter(pk=participation.pk).exists())
            executor = MigrationExecutor(connection)
            executor.migrate(current)
            reapplied = executor.loader.project_state(current).apps.get_model('projects', 'CourseProjectAssignment')
            self.assertFalse(reapplied.objects.get(pk=inactive.pk).is_active)
            self.assertIsNone(reapplied.objects.get(pk=inactive.pk).cancelled_at)
            self.assertEqual(reapplied.objects.get(pk=inactive.pk).cancellation_reason, '')
            self.assertEqual(reapplied.objects.get(pk=inactive.pk).lifecycle_version, 0)
            self.assertEqual(AuditLog.objects.get(pk=audit.pk).metadata['reason'], 'Prova iptali')

        finally:
            MigrationExecutor(connection).migrate(leaves)
