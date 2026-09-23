from datetime import timedelta
from queue import Queue
from threading import Barrier, Thread
from unittest import skipUnless

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from django.utils import timezone

from core.models import AuditLog
from projects.models import ProjectType

from .models import (
    CapstoneCheckpointEvaluation, CapstoneEnrollment, CapstoneProject,
    CapstoneProposal, CapstoneSubmissionAttempt, CapstoneSubmissionReview,
    CapstoneTask, CapstoneTerm,
)
from .services import (
    approve_capstone_proposal, complete_capstone_project, evaluate_capstone_checkpoint,
    submit_capstone_proposal, withdraw_capstone_proposal,
)
from .test_academic import academic_user


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row locks required.')
class CapstoneAcademicConcurrencyTests(TransactionTestCase):
    def setUp(self):
        now = timezone.now()
        self.term = CapstoneTerm.objects.create(academic_year='2026-2027', semester='FALL',
            starts_at=now - timedelta(days=14), midterm_at=now + timedelta(days=42),
            final_at=now + timedelta(days=98), is_active=True)
        self.student = academic_user('race-student', 'student', '4')
        self.advisor = academic_user('race-advisor', 'teacher')
        CapstoneEnrollment.objects.create(term=self.term, student=self.student)
        ProjectType.objects.get_or_create(code='CAPSTONE', defaults={'name': 'Bitirme Projesi', 'slug': 'capstone'})
        self.proposal = submit_capstone_proposal(student=self.student, advisor=self.advisor,
            term=self.term, title='Race test')

    def race(self, first, second):
        barrier = Barrier(2)
        results = Queue()

        def worker(action):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                results.put(('ok', action()))
            except ValidationError:
                results.put(('validation', None))
            except Exception as exc:
                results.put((type(exc).__name__, str(exc)))
            finally:
                connections.close_all()

        threads = [Thread(target=worker, args=(action,)) for action in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
            self.assertFalse(thread.is_alive())
        return [results.get_nowait() for _ in range(2)]

    def test_duplicate_approval_creates_one_project(self):
        result = self.race(
            lambda: approve_capstone_proposal(proposal=self.proposal, actor=self.advisor).pk,
            lambda: approve_capstone_proposal(proposal=self.proposal, actor=self.advisor).pk,
        )
        self.assertEqual([item[0] for item in result].count('ok'), 1)
        self.assertEqual(CapstoneProject.objects.count(), 1)
        self.assertEqual(CapstoneProposal.objects.get(pk=self.proposal.pk).status, 'APPROVED')

    def test_approval_withdrawal_race_has_consistent_result(self):
        result = self.race(
            lambda: approve_capstone_proposal(proposal=self.proposal, actor=self.advisor).pk,
            lambda: withdraw_capstone_proposal(proposal=self.proposal, student=self.student).pk,
        )
        self.assertEqual([item[0] for item in result].count('ok'), 1)
        proposal = CapstoneProposal.objects.get(pk=self.proposal.pk)
        self.assertIn(proposal.status, {'APPROVED', 'WITHDRAWN'})
        self.assertEqual(CapstoneProject.objects.count(), 1 if proposal.status == 'APPROVED' else 0)

    def _ready_project(self, all_checkpoints=False):
        project = approve_capstone_proposal(proposal=self.proposal, actor=self.advisor)
        for checkpoint in project.checkpoints.all() if all_checkpoints else project.checkpoints.all()[:1]:
            task = CapstoneTask.objects.create(capstone_project=project, checkpoint=checkpoint, created_by=self.advisor,
                title=f'Task {checkpoint.pk}', instructions='Rapor', due_at=checkpoint.due_at)
            attempt = CapstoneSubmissionAttempt.objects.create(task=task, submitted_by=self.student, attempt_number=1)
            CapstoneSubmissionReview.objects.create(submission_attempt=attempt, reviewed_by=self.advisor,
                decision='ACCEPTED', feedback='Uygun')
            if all_checkpoints:
                evaluate_capstone_checkpoint(checkpoint=checkpoint, actor=self.advisor, score=25, feedback='Yeterli')
        return project

    def test_duplicate_checkpoint_evaluation(self):
        project = self._ready_project()
        checkpoint = project.checkpoints.first()
        result = self.race(
            lambda: evaluate_capstone_checkpoint(checkpoint=checkpoint, actor=self.advisor, score=20, feedback='Yeterli').pk,
            lambda: evaluate_capstone_checkpoint(checkpoint=checkpoint, actor=self.advisor, score=21, feedback='Yeterli').pk,
        )
        self.assertEqual([item[0] for item in result].count('ok'), 1)
        self.assertEqual(CapstoneCheckpointEvaluation.objects.filter(checkpoint=checkpoint).count(), 1)

    def test_concurrent_completion_is_idempotent(self):
        project = self._ready_project(all_checkpoints=True)
        result = self.race(
            lambda: complete_capstone_project(capstone_project=project, actor=self.advisor).pk,
            lambda: complete_capstone_project(capstone_project=project, actor=self.advisor).pk,
        )
        self.assertEqual([item[0] for item in result].count('ok'), 2)
        self.assertEqual(AuditLog.objects.filter(action='capstone.project_completed', target_id=str(project.pk)).count(), 1)
