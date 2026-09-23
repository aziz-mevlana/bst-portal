from datetime import timedelta
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    CapstoneEnrollment,
    CapstoneProposal,
    CapstoneProject,
    CapstoneSubmissionAttempt,
    CapstoneSubmissionFile,
    CapstoneSubmissionReview,
    CapstoneTask,
    CapstoneTerm,
)
from .services import approve_capstone_proposal
from .storage import PrivateFileSystemStorage
from .workflow import (
    CheckpointProgress,
    TaskWorkflowState,
    get_checkpoint_progress,
    get_task_workflow_state,
)


class CapstoneEndToEndIntegrationTests(TestCase):
    def setUp(self):
        self.private_directory = TemporaryDirectory()
        self.file_field = CapstoneSubmissionFile._meta.get_field('file')
        self.original_storage = self.file_field.storage
        self.file_field.storage = PrivateFileSystemStorage(
            location=self.private_directory.name
        )

        now = timezone.now()
        self.term = CapstoneTerm.objects.create(
            academic_year='2026-2027',
            semester=CapstoneTerm.Semester.FALL,
            starts_at=now - timedelta(weeks=2),
            midterm_at=now + timedelta(weeks=6),
            final_at=now + timedelta(weeks=14),
            is_active=True,
        )
        self.student = self.create_user('integration-student', 'student', '4')
        self.advisor = self.create_user('integration-advisor', 'teacher')
        self.outsider = self.create_user('integration-outsider', 'student', '4')
        CapstoneEnrollment.objects.create(term=self.term, student=self.student)

    def tearDown(self):
        self.file_field.storage = self.original_storage
        self.private_directory.cleanup()
        super().tearDown()

    def create_user(self, username, user_type, class_level=None):
        user = User.objects.create_user(
            username,
            password='StrongPassword123!',
        )
        user.profile.user_type = user_type
        user.profile.class_level = (
            class_level if user_type in {'student', 'staff_student'} else None
        )
        user.profile.save(update_fields=['user_type', 'class_level'])
        return user

    def login(self, user):
        self.client.force_login(user)

    def start_capstone(self):
        self.login(self.student)
        response = self.client.post(reverse('capstone:student_start'), {
            'title': 'Uçtan Uca Bitirme Projesi',
            'description': 'Deployment öncesi integration testi.',
            'advisor': self.advisor.pk,
        })
        self.assertRedirects(response, reverse('capstone:student_home'))
        proposal = CapstoneProposal.objects.get(student=self.student, term=self.term)
        approve_capstone_proposal(proposal=proposal, actor=self.advisor)
        return CapstoneProject.objects.get(project__created_by=self.student)

    def create_task_through_advisor(self, checkpoint, title='Integration görevi'):
        self.login(self.advisor)
        response = self.client.post(
            reverse('capstone:advisor_task_create', args=[checkpoint.pk]),
            {
                'title': title,
                'instructions': 'Dosyayı teslim edip geri bildirimi takip edin.',
                'required_file_count': 1,
                'due_at': checkpoint.due_at.strftime('%Y-%m-%dT%H:%M'),
            },
        )
        self.assertEqual(response.status_code, 302)
        return CapstoneTask.objects.get(checkpoint=checkpoint, title=title)

    def submit_through_student(self, task, filename):
        self.login(self.student)
        return self.client.post(
            reverse('capstone:student_task_submit', args=[task.pk]),
            {'files': [SimpleUploadedFile(filename, b'private integration content')]},
        )

    def review_through_advisor(self, attempt, decision, feedback):
        self.login(self.advisor)
        return self.client.post(
            reverse('capstone:advisor_submission_review', args=[attempt.pk]),
            {'decision': decision, 'feedback': feedback},
        )

    def test_full_revision_to_acceptance_workflow_across_ui_services_and_storage(self):
        capstone_project = self.start_capstone()
        self.assertEqual(capstone_project.checkpoints.count(), 4)
        checkpoint = capstone_project.checkpoints.order_by('due_at').first()
        task = self.create_task_through_advisor(checkpoint)

        first_response = self.submit_through_student(task, 'ilk-rapor.pdf')
        self.assertEqual(first_response.status_code, 302)
        first_attempt = task.submission_attempts.get(attempt_number=1)
        first_file = first_attempt.files.get()
        first_snapshot = (
            first_attempt.task_id,
            first_attempt.submitted_by_id,
            first_attempt.attempt_number,
            first_attempt.submitted_at,
            first_attempt.is_late,
        )

        blocked_outstanding = self.submit_through_student(task, 'erken-ikinci.pdf')
        self.assertEqual(blocked_outstanding.status_code, 302)
        self.assertEqual(task.submission_attempts.count(), 1)

        self.login(self.advisor)
        download_response = self.client.get(
            reverse('capstone:submission_file_download', args=[first_file.pk])
        )
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(
            b''.join(download_response.streaming_content),
            b'private integration content',
        )
        download_response.close()

        revision_response = self.review_through_advisor(
            first_attempt,
            CapstoneSubmissionReview.Decision.REVISION_REQUIRED,
            'Analiz bölümünü geliştirip yeniden teslim edin.',
        )
        self.assertEqual(revision_response.status_code, 302)
        first_review = first_attempt.review
        review_snapshot = (
            first_review.submission_attempt_id,
            first_review.reviewed_by_id,
            first_review.decision,
            first_review.feedback,
            first_review.reviewed_at,
        )

        second_response = self.submit_through_student(task, 'ikinci-rapor.pdf')
        self.assertEqual(second_response.status_code, 302)
        second_attempt = task.submission_attempts.get(attempt_number=2)
        self.assertNotEqual(first_attempt.pk, second_attempt.pk)

        stale_response = self.review_through_advisor(
            first_attempt,
            CapstoneSubmissionReview.Decision.ACCEPTED,
            'Eski teslimi değiştirme denemesi.',
        )
        self.assertEqual(stale_response.status_code, 200)
        self.assertEqual(CapstoneSubmissionReview.objects.filter(
            submission_attempt=first_attempt,
        ).count(), 1)

        accepted_response = self.review_through_advisor(
            second_attempt,
            CapstoneSubmissionReview.Decision.ACCEPTED,
            'İkinci teslim kabul edildi.',
        )
        self.assertEqual(accepted_response.status_code, 302)
        second_review = second_attempt.review
        self.assertNotEqual(first_review.pk, second_review.pk)
        self.assertEqual(get_task_workflow_state(task), TaskWorkflowState.ACCEPTED)
        self.assertEqual(
            get_checkpoint_progress(checkpoint),
            CheckpointProgress.COMPLETED,
        )

        first_attempt.refresh_from_db()
        first_review.refresh_from_db()
        self.assertEqual(first_snapshot, (
            first_attempt.task_id,
            first_attempt.submitted_by_id,
            first_attempt.attempt_number,
            first_attempt.submitted_at,
            first_attempt.is_late,
        ))
        self.assertEqual(review_snapshot, (
            first_review.submission_attempt_id,
            first_review.reviewed_by_id,
            first_review.decision,
            first_review.feedback,
            first_review.reviewed_at,
        ))

        self.login(self.outsider)
        self.assertEqual(
            self.client.get(
                reverse('capstone:submission_file_download', args=[first_file.pk])
            ).status_code,
            404,
        )

        blocked_after_acceptance = self.submit_through_student(task, 'ucuncu-rapor.pdf')
        self.assertEqual(blocked_after_acceptance.status_code, 302)
        self.assertEqual(
            list(task.submission_attempts.order_by('attempt_number').values_list(
                'attempt_number', flat=True
            )),
            [1, 2],
        )

    def test_rejected_latest_attempt_allows_a_new_attempt(self):
        capstone_project = self.start_capstone()
        checkpoint = capstone_project.checkpoints.order_by('due_at').first()
        task = self.create_task_through_advisor(checkpoint, title='Rejected akışı')
        self.submit_through_student(task, 'rejected-first.pdf')
        first_attempt = task.submission_attempts.get(attempt_number=1)
        self.review_through_advisor(
            first_attempt,
            CapstoneSubmissionReview.Decision.REJECTED,
            'Yeni bir teslim hazırlayın.',
        )

        response = self.submit_through_student(task, 'rejected-second.pdf')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            list(task.submission_attempts.order_by('attempt_number').values_list(
                'attempt_number', flat=True
            )),
            [1, 2],
        )

    def test_state_changing_routes_do_not_mutate_on_get(self):
        self.login(self.student)
        response = self.client.get(reverse('capstone:student_start'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CapstoneProject.objects.exists())

        capstone_project = self.start_capstone()
        checkpoint = capstone_project.checkpoints.order_by('due_at').first()
        task = self.create_task_through_advisor(checkpoint, title='Method guard görevi')
        self.login(self.student)
        self.assertEqual(
            self.client.get(
                reverse('capstone:student_task_submit', args=[task.pk])
            ).status_code,
            405,
        )
        self.submit_through_student(task, 'method-guard.pdf')
        attempt = task.submission_attempts.get()
        self.login(self.advisor)
        self.assertEqual(
            self.client.get(
                reverse('capstone:advisor_task_create', args=[checkpoint.pk])
            ).status_code,
            405,
        )
        self.assertEqual(
            self.client.get(
                reverse('capstone:advisor_submission_review', args=[attempt.pk])
            ).status_code,
            405,
        )
