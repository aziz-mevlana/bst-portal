from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connection, connections
from django.test import TransactionTestCase

from .milestone_services import review_milestone, submit_milestone
from .models import Project, ProjectMilestone, ProjectMilestoneReview, ProjectMilestoneSubmission, ProjectType


class PostgreSQLMilestoneConcurrencyTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != 'postgresql':
            self.skipTest('PostgreSQL concurrency test requires PostgreSQL')
        self.student = User.objects.create_user('concurrent-student', password='password')
        self.student.profile.user_type = 'student'
        self.student.profile.class_level = '2'
        self.student.profile.save()
        self.teacher = User.objects.create_user('concurrent-teacher', password='password')
        self.teacher.profile.user_type = 'teacher'
        self.teacher.profile.save()
        kind, _ = ProjectType.objects.get_or_create(
            code='RESEARCH', defaults={'name': 'Research', 'slug': 'research-concurrency'}
        )
        self.project = Project.objects.create(project_type=kind, title='Concurrent project', created_by=self.student, advisor=self.teacher)
        self.milestone = ProjectMilestone.objects.create(project=self.project, title='Step', order=1, max_score=100, created_by=self.teacher)

    def _parallel(self, callable_):
        barrier = Barrier(2)
        def run(_):
            barrier.wait()
            try:
                return callable_()
            except ValidationError:
                return None
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, range(2)))

    def test_two_simultaneous_submissions_create_one_attempt(self):
        results = self._parallel(lambda: submit_milestone(milestone=self.milestone, actor=self.student))
        self.assertEqual(sum(item is not None for item in results), 1)
        self.assertEqual(ProjectMilestoneSubmission.objects.filter(milestone=self.milestone).count(), 1)

    def test_two_simultaneous_reviews_create_one_review(self):
        submission = submit_milestone(milestone=self.milestone, actor=self.student)
        results = self._parallel(lambda: review_milestone(submission=submission, actor=self.teacher, outcome='APPROVED', score=80))
        self.assertEqual(sum(item is not None for item in results), 1)
        self.assertEqual(ProjectMilestoneReview.objects.filter(submission=submission).count(), 1)

    def test_submission_and_review_race_preserves_attempt_order(self):
        first = submit_milestone(milestone=self.milestone, actor=self.student)
        barrier = Barrier(2)
        def submit():
            barrier.wait()
            try:
                return submit_milestone(milestone=self.milestone, actor=self.student)
            except ValidationError:
                return None
            finally:
                connections.close_all()
        def review():
            barrier.wait()
            try:
                return review_milestone(submission=first, actor=self.teacher, outcome='APPROVED', score=80)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            submit_future = pool.submit(submit)
            review_future = pool.submit(review)
            second = submit_future.result()
            review_future.result()
        self.assertEqual(ProjectMilestoneReview.objects.filter(submission=first).count(), 1)
        self.assertIsNone(second)
        self.assertEqual(ProjectMilestoneSubmission.objects.filter(milestone=self.milestone).count(), 1)
