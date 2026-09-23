from datetime import timedelta
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from projects.models import ProjectType

from .models import (
    CapstoneEnrollment,
    CapstoneProject,
    CapstoneProposal,
    CapstoneSubmissionAttempt,
    CapstoneSubmissionFile,
    CapstoneSubmissionReview,
    CapstoneTask,
    CapstoneTerm,
)
from .services import (
    create_capstone_project,
    create_capstone_submission,
    review_capstone_submission,
)
from .storage import PrivateFileSystemStorage


class CapstoneStudentViewTests(TestCase):
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
        self.owner = self.create_user('student-ui-owner', 'student', class_level='4')
        self.other_student = self.create_user(
            'student-ui-other', 'student', class_level='4'
        )
        self.ineligible = self.create_user(
            'student-ui-ineligible', 'student', class_level='3'
        )
        self.advisor = self.create_user('student-ui-advisor', 'teacher')
        self.other_teacher = self.create_user('student-ui-teacher', 'teacher')
        self.inactive_teacher = self.create_user('student-ui-inactive-teacher', 'teacher')
        self.inactive_teacher.is_active = False
        self.inactive_teacher.save(update_fields=['is_active'])
        CapstoneEnrollment.objects.create(term=self.term, student=self.owner)
        CapstoneEnrollment.objects.create(term=self.term, student=self.other_student)

        self.home_url = reverse('capstone:student_home')
        self.start_url = reverse('capstone:student_start')

    def tearDown(self):
        self.file_field.storage = self.original_storage
        self.private_directory.cleanup()
        super().tearDown()

    def create_user(self, username, user_type, *, class_level=None, **user_fields):
        user = User.objects.create_user(
            username,
            password='StrongPassword123!',
            **user_fields,
        )
        user.profile.user_type = user_type
        user.profile.class_level = (
            class_level if user_type in {'student', 'staff_student'} else None
        )
        user.profile.save(update_fields=['user_type', 'class_level'])
        return user

    def login(self, user=None):
        self.client.force_login(user or self.owner)

    def create_project(self, *, student=None, title='Öğrenci Bitirme Projesi'):
        return create_capstone_project(
            student=student or self.owner,
            advisor=self.advisor,
            title=title,
            description='Öğrenci dashboard açıklaması.',
            term=self.term,
        )

    def create_task(self, capstone_project=None, **overrides):
        capstone_project = capstone_project or self.create_project()
        checkpoint = capstone_project.checkpoints.order_by('due_at').first()
        values = {
            'capstone_project': capstone_project,
            'checkpoint': checkpoint,
            'created_by': self.advisor,
            'title': 'Rapor teslimi',
            'instructions': 'Raporun güncel sürümünü teslim edin.',
            'required_file_count': 1,
            'due_at': checkpoint.due_at,
        }
        values.update(overrides)
        return CapstoneTask.objects.create(**values)

    def upload(self, name='rapor.pdf', content=b'capstone-report'):
        return SimpleUploadedFile(name, content)

    def submit(self, task):
        return create_capstone_submission(
            task=task,
            student=self.owner,
            files=[self.upload()],
        )

    def review(self, attempt, decision):
        return review_capstone_submission(
            submission_attempt=attempt,
            reviewer=self.advisor,
            decision=decision,
            feedback='Danışman geri bildirimi.',
        )

    def test_home_shows_start_cta_only_to_eligible_student_without_project(self):
        self.login()
        response = self.client.get(self.home_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bitirme projenizi başlatın')
        self.assertContains(response, self.start_url)

        self.login(self.ineligible)
        response = self.client.get(self.home_url)
        self.assertContains(response, 'aktif bitirme projesi kaydınız bulunmuyor')
        self.assertNotContains(response, self.start_url)

    def test_existing_project_renders_owner_dashboard(self):
        capstone_project = self.create_project()
        self.login()

        response = self.client.get(self.home_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, capstone_project.project.title)
        self.assertContains(response, self.advisor.username)
        self.assertContains(response, str(self.term))

    def test_anonymous_home_uses_authentication_redirect(self):
        response = self.client.get(self.home_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_start_get_limits_advisors_to_active_non_admin_teachers(self):
        admin_teacher = self.create_user(
            'student-ui-admin-teacher', 'teacher', is_staff=True
        )
        self.login()

        response = self.client.get(self.start_url)

        self.assertEqual(response.status_code, 200)
        advisor_ids = set(
            response.context['form'].fields['advisor'].queryset.values_list('pk', flat=True)
        )
        self.assertIn(self.advisor.pk, advisor_ids)
        self.assertIn(self.other_teacher.pk, advisor_ids)
        self.assertNotIn(self.owner.pk, advisor_ids)
        self.assertNotIn(self.inactive_teacher.pk, advisor_ids)
        self.assertNotIn(admin_teacher.pk, advisor_ids)

    def test_valid_start_submits_proposal_before_project_creation(self):
        self.login()

        response = self.client.post(self.start_url, {
            'title': 'Yeni Bitirme Projesi',
            'description': 'Merkezi servis üzerinden.',
            'advisor': self.advisor.pk,
        })

        self.assertRedirects(response, self.home_url)
        proposal = CapstoneProposal.objects.get(student=self.owner)
        self.assertEqual(proposal.requested_advisor, self.advisor)
        self.assertEqual(proposal.status, CapstoneProposal.Status.PENDING)
        self.assertFalse(CapstoneProject.objects.filter(project__created_by=self.owner).exists())

    def test_manipulated_invalid_advisor_is_rejected_as_form_error(self):
        self.login()

        response = self.client.post(self.start_url, {
            'title': 'Manipüle Proje',
            'description': 'Geçersiz danışman.',
            'advisor': self.other_student.pk,
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(CapstoneProject.objects.filter(project__created_by=self.owner).exists())

    def test_duplicate_and_noneligible_start_are_blocked(self):
        self.create_project()
        self.login()
        response = self.client.post(self.start_url, {
            'title': 'İkinci Proje',
            'advisor': self.advisor.pk,
        })
        self.assertRedirects(response, self.home_url)
        self.assertEqual(
            CapstoneProject.objects.filter(project__created_by=self.owner).count(), 1
        )

        self.login(self.ineligible)
        response = self.client.get(self.start_url)
        self.assertRedirects(response, self.home_url)

    def test_unrelated_student_cannot_see_another_students_dashboard(self):
        capstone_project = self.create_project(title='Gizli Öğrenci Projesi')
        self.login(self.other_student)

        response = self.client.get(self.home_url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, capstone_project.project.title)
        self.assertContains(response, 'Bitirme projenizi başlatın')

    def test_dashboard_renders_checkpoint_task_state_overdue_and_history(self):
        task = self.create_task()
        CapstoneTask.objects.filter(pk=task.pk).update(due_at=timezone.now() - timedelta(days=1))
        task.refresh_from_db()
        attempt = self.submit(task)
        self.review(attempt, CapstoneSubmissionReview.Decision.REVISION_REQUIRED)
        submission_file = attempt.files.get()
        self.login()

        response = self.client.get(self.home_url)

        self.assertContains(response, task.checkpoint.get_kind_display())
        self.assertContains(response, task.title)
        self.assertContains(response, 'Revizyon gerekli')
        self.assertContains(response, 'son teslim tarihi geçti')
        self.assertContains(response, '1. teslim')
        self.assertContains(response, 'Danışman geri bildirimi.')
        download_url = reverse(
            'capstone:submission_file_download', args=[submission_file.pk]
        )
        self.assertContains(response, download_url)
        self.assertNotContains(response, '/media/')

    def test_not_submitted_task_can_be_submitted_and_redirects_to_anchor(self):
        task = self.create_task()
        self.login()

        response = self.client.post(
            reverse('capstone:student_task_submit', args=[task.pk]),
            {'files': [self.upload()]},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f'{self.home_url}#task-{task.pk}')
        attempt = CapstoneSubmissionAttempt.objects.get(task=task)
        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(attempt.files.count(), 1)

    def test_revision_required_and_rejected_allow_new_submission(self):
        capstone_project = self.create_project()
        for decision in (
            CapstoneSubmissionReview.Decision.REVISION_REQUIRED,
            CapstoneSubmissionReview.Decision.REJECTED,
        ):
            with self.subTest(decision=decision):
                task = self.create_task(
                    capstone_project=capstone_project,
                    title=f'Görev {decision}',
                )
                first = self.submit(task)
                self.review(first, decision)
                self.login()

                response = self.client.post(
                    reverse('capstone:student_task_submit', args=[task.pk]),
                    {'files': [self.upload(name=f'{decision}.pdf')]},
                )

                self.assertEqual(response.status_code, 302)
                self.assertEqual(task.submission_attempts.count(), 2)

    def test_awaiting_review_and_accepted_block_new_submission(self):
        capstone_project = self.create_project()
        for reviewed in (False, True):
            with self.subTest(reviewed=reviewed):
                task = self.create_task(
                    capstone_project=capstone_project,
                    title=f'Kapalı görev {reviewed}',
                )
                first = self.submit(task)
                if reviewed:
                    self.review(first, CapstoneSubmissionReview.Decision.ACCEPTED)
                self.login()

                response = self.client.post(
                    reverse('capstone:student_task_submit', args=[task.pk]),
                    {'files': [self.upload(name=f'blocked-{reviewed}.pdf')]},
                )

                self.assertEqual(response.status_code, 302)
                self.assertEqual(task.submission_attempts.count(), 1)

    def test_wrong_file_count_returns_controlled_error_without_attempt(self):
        task = self.create_task(required_file_count=2)
        self.login()

        response = self.client.post(
            reverse('capstone:student_task_submit', args=[task.pk]),
            {'files': [self.upload()]},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(task.submission_attempts.exists())

    def test_unrelated_student_and_advisor_get_not_found_on_student_submit(self):
        task = self.create_task()
        submit_url = reverse('capstone:student_task_submit', args=[task.pk])

        for user in (self.other_student, self.advisor):
            with self.subTest(user=user.username):
                self.login(user)
                response = self.client.post(submit_url, {'files': [self.upload()]})
                self.assertEqual(response.status_code, 404)

        self.assertFalse(task.submission_attempts.exists())

    def test_dashboard_hides_upload_form_while_waiting_and_after_acceptance(self):
        task = self.create_task()
        first = self.submit(task)
        self.login()

        response = self.client.get(self.home_url)
        self.assertContains(response, 'Değerlendirme bekliyor')
        self.assertNotContains(
            response,
            reverse('capstone:student_task_submit', args=[task.pk]),
        )

        self.review(first, CapstoneSubmissionReview.Decision.ACCEPTED)
        response = self.client.get(self.home_url)
        self.assertContains(response, 'Kabul edildi')
        self.assertNotContains(
            response,
            reverse('capstone:student_task_submit', args=[task.pk]),
        )

    def test_ineligible_existing_owner_keeps_access_to_own_dashboard(self):
        capstone_project = self.create_project()
        self.owner.profile.class_level = '3'
        self.owner.profile.save(update_fields=['class_level'])
        self.login()

        response = self.client.get(self.home_url)

        self.assertContains(response, capstone_project.project.title)

    def test_missing_active_term_shows_neutral_state(self):
        self.term.is_active = False
        self.term.save(update_fields=['is_active', 'updated_at'])
        self.login()

        response = self.client.get(self.home_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aktif bitirme projesi kaydınız bulunmuyor')
        self.assertNotContains(response, self.start_url)
