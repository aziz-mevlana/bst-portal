from datetime import timedelta

from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class CapstoneAcademicMigrationTests(TransactionTestCase):
    before = [('capstone', '0006_capstonesubmissionreview')]
    after = [('capstone', '0007_capstonecheckpointevaluation_capstoneproposal_and_more')]

    def test_existing_project_and_checkpoint_remain_active(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        apps = executor.loader.project_state(self.before).apps
        Term = apps.get_model('capstone', 'CapstoneTerm')
        CapstoneProject = apps.get_model('capstone', 'CapstoneProject')
        Checkpoint = apps.get_model('capstone', 'CapstoneCheckpoint')
        Project = apps.get_model('projects', 'Project')
        ProjectType = apps.get_model('projects', 'ProjectType')
        student = User.objects.create_user('legacy-capstone-student')
        advisor = User.objects.create_user('legacy-capstone-advisor')
        now = timezone.now()
        term = Term.objects.create(academic_year='2026-2027', semester='FALL', starts_at=now,
            midterm_at=now + timedelta(days=60), final_at=now + timedelta(days=120), is_active=True)
        kind = ProjectType.objects.get(code='CAPSTONE')
        project = Project.objects.create(title='Existing academic project', slug='existing-academic-project',
            created_by_id=student.pk, advisor_id=advisor.pk, project_type_id=kind.pk,
            development_status='in_progress', visibility='private')
        capstone_project = CapstoneProject.objects.create(project_id=project.pk, term_id=term.pk)
        checkpoint = Checkpoint.objects.create(capstone_project_id=capstone_project.pk, kind='FIRST_REVIEW',
                                               due_at=now + timedelta(days=28))

        executor = MigrationExecutor(connection)
        executor.migrate(self.after)
        apps = executor.loader.project_state(self.after).apps
        CurrentProject = apps.get_model('capstone', 'CapstoneProject')
        CurrentCheckpoint = apps.get_model('capstone', 'CapstoneCheckpoint')
        Proposal = apps.get_model('capstone', 'CapstoneProposal')
        self.assertEqual(CurrentProject.objects.get(pk=capstone_project.pk).project_id, project.pk)
        self.assertIsNone(CurrentProject.objects.get(pk=capstone_project.pk).completed_at)
        self.assertEqual(CurrentCheckpoint.objects.get(pk=checkpoint.pk).max_score, 25)
        self.assertFalse(Proposal.objects.exists())
        MigrationExecutor(connection).migrate(self.before)
        MigrationExecutor(connection).migrate(self.after)
