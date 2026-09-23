from datetime import timedelta
from queue import Queue
from threading import Barrier, Thread
from unittest import skipUnless

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from django.utils import timezone

from projects.models import ProjectType
from .academic_models import CapstoneAcademicReview, CapstoneAcademicSubmission
from .academic_services import (claim_student, initialize_project, review_checkpoint,
    save_plan_checkpoint, submit_checkpoint, unassign_student)
from .models import CapstoneEnrollment, CapstoneProject, CapstoneTerm
from .test_academic_v3 import user


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row locks required.')
class AcademicV3ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        now = timezone.now()
        self.term = CapstoneTerm.objects.create(academic_year='2026-2027', semester='FALL',
            starts_at=now - timedelta(days=2), midterm_at=now + timedelta(days=30),
            final_at=now + timedelta(days=90), is_active=True)
        self.student = user('v3-race-student', 'student', '4')
        self.teacher = user('v3-race-teacher', 'teacher')
        self.other_teacher = user('v3-race-other', 'teacher')
        self.enrollment = CapstoneEnrollment.objects.create(term=self.term, student=self.student)
        ProjectType.objects.get_or_create(code='CAPSTONE', defaults={'name': 'Bitirme Projesi', 'slug': 'capstone'})

    def race(self, left, right):
        barrier, result = Barrier(2), Queue()
        def worker(action):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                result.put(('ok', action()))
            except (ValidationError, PermissionDenied):
                result.put(('rejected', None))
            except Exception as exc:
                result.put((type(exc).__name__, str(exc)))
            finally:
                connections.close_all()
        threads = [Thread(target=worker, args=(action,)) for action in (left, right)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
            self.assertFalse(thread.is_alive())
        return [result.get_nowait() for _ in threads]

    def project_and_checkpoint(self):
        claim_student(enrollment=self.enrollment, advisor=self.teacher)
        project = initialize_project(enrollment=self.enrollment, student=self.student,
                                     title='Yarış testi', description='Amaç')
        plan = self.teacher.capstone_plans.get(term=self.term)
        checkpoint = save_plan_checkpoint(plan=plan, actor=self.teacher, title='Rapor', description='',
                                         order=1, due_at=timezone.now() + timedelta(days=5))
        return project, plan, checkpoint

    def test_two_teachers_claim_one_student(self):
        results = self.race(lambda: claim_student(enrollment=self.enrollment, advisor=self.teacher).pk,
                            lambda: claim_student(enrollment=self.enrollment, advisor=self.other_teacher).pk)
        self.assertEqual([status for status, _ in results].count('ok'), 1)
        self.assertEqual([status for status, _ in results].count('rejected'), 1)
        self.assertIn(CapstoneEnrollment.objects.get(pk=self.enrollment.pk).advisor_id,
                      {self.teacher.pk, self.other_teacher.pk})

    def test_double_project_initialization(self):
        claim_student(enrollment=self.enrollment, advisor=self.teacher)
        results = self.race(
            lambda: initialize_project(enrollment=self.enrollment, student=self.student, title='Bir', description='Amaç').pk,
            lambda: initialize_project(enrollment=self.enrollment, student=self.student, title='İki', description='Amaç').pk)
        self.assertEqual([status for status, _ in results].count('ok'), 1)
        self.assertEqual(CapstoneProject.objects.count(), 1)

    def test_unassign_initialize_race(self):
        claim_student(enrollment=self.enrollment, advisor=self.teacher)
        results = self.race(
            lambda: initialize_project(enrollment=self.enrollment, student=self.student, title='Bir', description='Amaç').pk,
            lambda: unassign_student(enrollment=self.enrollment, actor=self.teacher).pk)
        self.assertEqual([status for status, _ in results].count('ok'), 1)
        enrollment = CapstoneEnrollment.objects.get(pk=self.enrollment.pk)
        self.assertEqual(bool(enrollment.advisor_id), CapstoneProject.objects.exists())

    def test_duplicate_submission(self):
        project, _, checkpoint = self.project_and_checkpoint()
        results = self.race(
            lambda: submit_checkpoint(project=project, checkpoint=checkpoint, student=self.student, note='Bir').pk,
            lambda: submit_checkpoint(project=project, checkpoint=checkpoint, student=self.student, note='İki').pk)
        self.assertEqual([status for status, _ in results].count('ok'), 1)
        self.assertEqual(CapstoneAcademicSubmission.objects.count(), 1)

    def test_duplicate_approval(self):
        project, _, checkpoint = self.project_and_checkpoint()
        submission = submit_checkpoint(project=project, checkpoint=checkpoint, student=self.student, note='Rapor')
        results = self.race(
            lambda: review_checkpoint(submission=submission, actor=self.teacher, decision='APPROVED', feedback='Uygun').pk,
            lambda: review_checkpoint(submission=submission, actor=self.teacher, decision='APPROVED', feedback='Uygun').pk)
        self.assertEqual([status for status, _ in results].count('ok'), 1)
        self.assertEqual(CapstoneAcademicReview.objects.count(), 1)

    def test_review_submission_race(self):
        project, _, checkpoint = self.project_and_checkpoint()
        submission = submit_checkpoint(project=project, checkpoint=checkpoint, student=self.student, note='Bir')
        results = self.race(
            lambda: review_checkpoint(submission=submission, actor=self.teacher,
                                      decision='REVISION_REQUIRED', feedback='Düzeltin').pk,
            lambda: submit_checkpoint(project=project, checkpoint=checkpoint,
                                      student=self.student, note='İki').pk)
        self.assertIn([status for status, _ in results].count('ok'), {1, 2})
        self.assertLessEqual(CapstoneAcademicSubmission.objects.count(), 2)
        self.assertEqual(CapstoneAcademicReview.objects.count(), 1)
        if CapstoneAcademicSubmission.objects.count() == 2:
            self.assertEqual(list(CapstoneAcademicSubmission.objects.values_list('attempt_number', flat=True)), [1, 2])

    def test_shared_date_update_and_progress(self):
        project, plan, checkpoint = self.project_and_checkpoint()
        updated_due = timezone.now() + timedelta(days=8)
        results = self.race(
            lambda: save_plan_checkpoint(plan=plan, checkpoint=checkpoint, actor=self.teacher,
                title=checkpoint.title, description='', order=1, due_at=updated_due).pk,
            lambda: submit_checkpoint(project=project, checkpoint=checkpoint,
                                      student=self.student, note='Rapor').pk)
        self.assertEqual([status for status, _ in results].count('ok'), 2, results)
        self.assertEqual(CapstoneAcademicSubmission.objects.count(), 1)
        checkpoint.refresh_from_db()
        self.assertEqual(checkpoint.due_at, updated_due)
