from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class LegacyCourseMigrationTests(TransactionTestCase):
    migrate_from = [('projects', '0024_alter_team_role_fields')]
    migrate_to = [('projects', '0025_course_project_course_alter_projectrequest_course_and_more')]

    def test_normalizes_legacy_strings_and_backfills_certain_project(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        apps = executor.loader.project_state(self.migrate_from).apps
        ProjectType = apps.get_model('projects', 'ProjectType')
        ProjectRequest = apps.get_model('projects', 'ProjectRequest')
        Project = apps.get_model('projects', 'Project')
        owner = User.objects.create_user('migration-owner', password='password')
        # Transactional migration tests may have flushed data seeded by older migrations.
        course_type, _ = ProjectType.objects.get_or_create(
            code='COURSE', defaults={'name': 'Ders Projesi', 'slug': 'ders-projesi', 'requires_course': True})
        research_type, _ = ProjectType.objects.get_or_create(
            code='RESEARCH', defaults={'name': 'Araştırma Projesi', 'slug': 'arastirma-projesi'})
        first = ProjectRequest.objects.create(project_type=course_type, title='First', course='  Software Engineering  ')
        second = ProjectRequest.objects.create(project_type=course_type, title='Second', course='software engineering')
        empty = ProjectRequest.objects.create(project_type=course_type, title='Empty', course='   ')
        anomaly = ProjectRequest.objects.create(project_type=research_type, title='Old mismatch', course='  Legacy Other  ')
        project = Project.objects.create(project_type=course_type, project_request=first, title='Old project', slug='old-course-project', created_by_id=owner.pk)
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        apps = executor.loader.project_state(self.migrate_to).apps
        Course = apps.get_model('projects', 'Course')
        ProjectRequest = apps.get_model('projects', 'ProjectRequest')
        Project = apps.get_model('projects', 'Project')
        self.assertEqual(Course.objects.count(), 2)
        self.assertEqual(ProjectRequest.objects.get(pk=first.pk).course_id, ProjectRequest.objects.get(pk=second.pk).course_id)
        self.assertIsNone(ProjectRequest.objects.get(pk=empty.pk).course_id)
        self.assertIsNone(ProjectRequest.objects.get(pk=anomaly.pk).course_id)
        self.assertEqual(ProjectRequest.objects.get(pk=anomaly.pk).legacy_course_unmapped, '  Legacy Other  ')
        self.assertEqual(Project.objects.get(pk=project.pk).course_id, ProjectRequest.objects.get(pk=first.pk).course_id)
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldRequest = old_apps.get_model('projects', 'ProjectRequest')
        self.assertEqual(OldRequest.objects.get(pk=first.pk).course, '  Software Engineering  ')
        self.assertEqual(OldRequest.objects.get(pk=empty.pk).course, '   ')
        self.assertEqual(OldRequest.objects.get(pk=anomaly.pk).course, '  Legacy Other  ')
        MigrationExecutor(connection).migrate(self.migrate_to)
