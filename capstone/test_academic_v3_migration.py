from datetime import timedelta

from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.exceptions import IrreversibleError
from django.test import TransactionTestCase
from django.utils import timezone


class AcademicV3MigrationTests(TransactionTestCase):
    before = [('capstone', '0007_capstonecheckpointevaluation_capstoneproposal_and_more')]
    after = [('capstone', '0008_capstoneenrollment_advisor_and_more')]

    def test_existing_project_and_history_are_preserved_and_advisor_backfilled(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        apps = executor.loader.project_state(self.before).apps
        Term = apps.get_model('capstone', 'CapstoneTerm')
        Enrollment = apps.get_model('capstone', 'CapstoneEnrollment')
        CapstoneProject = apps.get_model('capstone', 'CapstoneProject')
        Checkpoint = apps.get_model('capstone', 'CapstoneCheckpoint')
        Project = apps.get_model('projects', 'Project')
        ProjectType = apps.get_model('projects', 'ProjectType')
        student = User.objects.create_user('v3-migration-student')
        advisor = User.objects.create_user('v3-migration-advisor')
        now = timezone.now()
        term = Term.objects.create(academic_year='2026-2027', semester='FALL', starts_at=now,
            midterm_at=now + timedelta(days=60), final_at=now + timedelta(days=120), is_active=True)
        enrollment = Enrollment.objects.create(term_id=term.pk, student_id=student.pk)
        project_type, _ = ProjectType.objects.get_or_create(code='CAPSTONE', defaults={
            'name': 'Bitirme Projesi', 'slug': 'capstone', 'requires_advisor': True})
        base = Project.objects.create(title='Eski Bitirme Projesi', slug='eski-bitirme-v3',
            created_by_id=student.pk, advisor_id=advisor.pk, project_type_id=project_type.pk,
            development_status='in_progress', visibility='private')
        project = CapstoneProject.objects.create(project_id=base.pk, term_id=term.pk)
        checkpoint = Checkpoint.objects.create(capstone_project_id=project.pk, kind='FIRST_REVIEW',
                                                due_at=now + timedelta(days=28), max_score=25)

        executor = MigrationExecutor(connection)
        executor.migrate(self.after)
        apps = executor.loader.project_state(self.after).apps
        CurrentEnrollment = apps.get_model('capstone', 'CapstoneEnrollment')
        self.assertEqual(CurrentEnrollment.objects.get(pk=enrollment.pk).advisor_id, advisor.pk)
        self.assertEqual(apps.get_model('capstone', 'CapstoneProject').objects.get(pk=project.pk).project_id, base.pk)
        self.assertEqual(apps.get_model('capstone', 'CapstoneCheckpoint').objects.get(pk=checkpoint.pk).max_score, 25)
        self.assertEqual(apps.get_model('capstone', 'CapstonePlanCheckpoint').objects.count(), 0)
        self.assertEqual(apps.get_model('capstone', 'CapstoneProposal').objects.count(), 0)
        with self.assertRaises(IrreversibleError):
            MigrationExecutor(connection).migrate(self.before)
