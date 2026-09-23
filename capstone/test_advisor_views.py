from datetime import timedelta
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    CapstoneEnrollment,
    CapstoneProject,
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


class CapstoneAdvisorViewTests(TestCase):
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
        self.owner = self.create_user('advisor-ui-owner', 'student', class_level='4')
        self.other_student = self.create_user(
            'advisor-ui-other-student', 'student', class_level='4'
        )
        self.advisor = self.create_user('advisor-ui-assigned', 'teacher')
        self.other_advisor = self.create_user('advisor-ui-other-advisor', 'teacher')
        self.unrelated_teacher = self.create_user('advisor-ui-unrelated', 'teacher')
        self.inactive_teacher = self.create_user('advisor-ui-inactive', 'teacher')
        self.inactive_teacher.is_active = False
        self.inactive_teacher.save(update_fields=['is_active'])
        CapstoneEnrollment.objects.create(term=self.term, student=self.owner)
        CapstoneEnrollment.objects.create(term=self.term, student=self.other_student)

        self.capstone_project = self.create_project(
            student=self.owner,
            advisor=self.advisor,
            title='Danışmanın Bitirme Projesi',
        )
        self.other_project = self.create_project(
            student=self.other_student,
            advisor=self.other_advisor,
            title='Başka Danışmanın Projesi',
        )
        self.checkpoint = self.capstone_project.checkpoints.order_by('due_at').first()
        self.home_url = reverse('capstone:advisor_home')
        self.detail_url = reverse(
            'capstone:advisor_project_detail', args=[self.capstone_project.pk]
        )

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

    def create_project(self, *, student, advisor, title):
        return create_capstone_project(
            student=student,
            advisor=advisor,
            title=title,
            description='Danışman ekranı test açıklaması.',
            term=self.term,
        )

    def create_task(self, **overrides):
        values = {
            'capstone_project': self.capstone_project,
            'checkpoint': self.checkpoint,
            'created_by': self.advisor,
            'title': 'Danışman görevi',
            'instructions': 'Raporu ve eklerini teslim edin.',
            'required_file_count': 1,
            'due_at': self.checkpoint.due_at,
        }
        values.update(overrides)
        return CapstoneTask.objects.create(**values)

    def submit(self, task, *, name='advisor-review.pdf'):
        return create_capstone_submission(
            task=task,
            student=self.owner,
            files=[SimpleUploadedFile(name, b'advisor-review-content')],
        )

    def login(self, user=None):
        self.client.force_login(user or self.advisor)

    def task_payload(self, **overrides):
        values = {
            'title': 'Yeni danışman görevi',
            'instructions': 'Belirtilen çalışmaları tamamlayın.',
            'required_file_count': 2,
            'due_at': self.checkpoint.due_at.strftime('%Y-%m-%dT%H:%M'),
        }
        values.update(overrides)
        return values

    def test_advisor_home_lists_only_assigned_projects_with_summary(self):
        task = self.create_task(due_at=timezone.now() - timedelta(days=1))
        self.submit(task)
        self.login()

        response = self.client.get(self.home_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.capstone_project.project.title)
        self.assertNotContains(response, self.other_project.project.title)
        self.assertContains(response, '1 değerlendirme bekliyor')
        self.assertContains(response, 'Geciken görev')

    def test_unrelated_teacher_sees_empty_advisor_home(self):
        self.login(self.unrelated_teacher)

        response = self.client.get(self.home_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Size atanmış bir bitirme projesi bulunmuyor.')
        self.assertNotContains(response, self.capstone_project.project.title)

    def test_student_and_inactive_teacher_cannot_access_advisor_home(self):
        self.login(self.owner)
        self.assertEqual(self.client.get(self.home_url).status_code, 404)

        self.login(self.inactive_teacher)
        response = self.client.get(self.home_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

        staff_teacher = self.create_user(
            'advisor-ui-staff-teacher', 'teacher', is_staff=True
        )
        self.login(staff_teacher)
        self.assertEqual(self.client.get(self.home_url).status_code, 200)

    def test_anonymous_advisor_home_redirects_to_login(self):
        response = self.client.get(self.home_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_assigned_advisor_can_open_project_detail(self):
        self.login()

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.capstone_project.project.title)
        self.assertContains(response, self.owner.username)
        self.assertContains(response, self.checkpoint.get_kind_display())

    def test_unrelated_teacher_and_student_get_not_found_for_detail(self):
        for user in (self.unrelated_teacher, self.owner):
            with self.subTest(user=user.username):
                self.login(user)
                self.assertEqual(self.client.get(self.detail_url).status_code, 404)

    def test_detail_renders_workflow_submission_files_and_feedback_history(self):
        task = self.create_task()
        attempt = self.submit(task)
        review_capstone_submission(
            submission_attempt=attempt,
            reviewer=self.advisor,
            decision=CapstoneSubmissionReview.Decision.REVISION_REQUIRED,
            feedback='Kaynakçayı ve analiz bölümünü güncelleyin.',
        )
        submission_file = attempt.files.get()
        self.login()

        response = self.client.get(self.detail_url)

        self.assertContains(response, task.title)
        self.assertContains(response, 'Revizyon gerekli')
        self.assertContains(response, '1. teslim')
        self.assertContains(response, 'Kaynakçayı ve analiz bölümünü güncelleyin.')
        download_url = reverse(
            'capstone:submission_file_download', args=[submission_file.pk]
        )
        self.assertContains(response, download_url)
        self.assertNotContains(response, '/media/')

    def test_assigned_advisor_can_create_task_with_server_side_creator(self):
        self.login()
        create_url = reverse(
            'capstone:advisor_task_create', args=[self.checkpoint.pk]
        )

        response = self.client.post(create_url, self.task_payload())

        task = CapstoneTask.objects.get(title='Yeni danışman görevi')
        self.assertEqual(response.status_code, 302)
        self.assertIn(self.detail_url, response.url)
        self.assertEqual(task.created_by, self.advisor)
        self.assertEqual(task.checkpoint, self.checkpoint)

    def test_task_create_rejects_invalid_file_count_and_late_due_date(self):
        self.login()
        create_url = reverse(
            'capstone:advisor_task_create', args=[self.checkpoint.pk]
        )

        response = self.client.post(
            create_url,
            self.task_payload(required_file_count=0),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '1 değerinden büyük veya eşit')
        self.assertFalse(CapstoneTask.objects.filter(title='Yeni danışman görevi').exists())

        response = self.client.post(
            create_url,
            self.task_payload(
                due_at=(self.checkpoint.due_at + timedelta(days=1)).strftime(
                    '%Y-%m-%dT%H:%M'
                )
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'değerlendirme aşamasının tarihinden sonra olamaz')
        self.assertFalse(CapstoneTask.objects.filter(title='Yeni danışman görevi').exists())

    def test_unrelated_teacher_student_and_other_project_checkpoint_are_hidden(self):
        create_url = reverse(
            'capstone:advisor_task_create', args=[self.checkpoint.pk]
        )
        for user in (self.unrelated_teacher, self.owner):
            with self.subTest(user=user.username):
                self.login(user)
                self.assertEqual(
                    self.client.post(create_url, self.task_payload()).status_code,
                    404,
                )

        other_checkpoint = self.other_project.checkpoints.order_by('due_at').first()
        self.login()
        response = self.client.post(
            reverse('capstone:advisor_task_create', args=[other_checkpoint.pk]),
            self.task_payload(),
        )
        self.assertEqual(response.status_code, 404)

    def test_completed_checkpoint_rejects_new_task(self):
        task = self.create_task()
        attempt = self.submit(task)
        review_capstone_submission(
            submission_attempt=attempt,
            reviewer=self.advisor,
            decision=CapstoneSubmissionReview.Decision.ACCEPTED,
            feedback='Görev tamamlandı.',
        )
        self.login()

        response = self.client.post(
            reverse('capstone:advisor_task_create', args=[self.checkpoint.pk]),
            self.task_payload(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tamamlanmış değerlendirme aşamasına yeni görev eklenemez')
        self.assertEqual(self.checkpoint.tasks.count(), 1)

    def test_review_endpoint_accepts_all_defined_decisions_with_prg(self):
        decisions = (
            CapstoneSubmissionReview.Decision.ACCEPTED,
            CapstoneSubmissionReview.Decision.REVISION_REQUIRED,
            CapstoneSubmissionReview.Decision.REJECTED,
        )
        self.login()
        for index, decision in enumerate(decisions, start=1):
            with self.subTest(decision=decision):
                checkpoint = self.capstone_project.checkpoints.all()[index]
                task = self.create_task(
                    checkpoint=checkpoint,
                    due_at=checkpoint.due_at,
                    title=f'Review görevi {index}',
                )
                attempt = self.submit(task, name=f'review-{index}.pdf')
                response = self.client.post(
                    reverse('capstone:advisor_submission_review', args=[attempt.pk]),
                    {'decision': decision, 'feedback': f'{decision} geri bildirimi'},
                )

                self.assertEqual(response.status_code, 302)
                self.assertEqual(attempt.review.decision, decision)
                self.assertEqual(attempt.review.reviewed_by, self.advisor)

    def test_review_form_rejects_blank_feedback_and_invalid_decision(self):
        self.login()
        for payload in (
            {'decision': CapstoneSubmissionReview.Decision.ACCEPTED, 'feedback': '   '},
            {'decision': 'MANIPULATED', 'feedback': 'Geçersiz karar.'},
        ):
            with self.subTest(payload=payload):
                task = self.create_task(title=f'Form görevi {payload["decision"]}')
                attempt = self.submit(task, name=f'{attempt_name(payload)}.pdf')
                response = self.client.post(
                    reverse('capstone:advisor_submission_review', args=[attempt.pk]),
                    payload,
                )
                self.assertEqual(response.status_code, 200)
                self.assertFalse(
                    CapstoneSubmissionReview.objects.filter(
                        submission_attempt=attempt
                    ).exists()
                )

    def test_unrelated_teacher_and_student_cannot_review(self):
        task = self.create_task()
        attempt = self.submit(task)
        review_url = reverse(
            'capstone:advisor_submission_review', args=[attempt.pk]
        )
        payload = {
            'decision': CapstoneSubmissionReview.Decision.ACCEPTED,
            'feedback': 'Yetkisiz değerlendirme.',
        }

        for user in (self.unrelated_teacher, self.owner):
            with self.subTest(user=user.username):
                self.login(user)
                self.assertEqual(self.client.post(review_url, payload).status_code, 404)
        self.assertFalse(CapstoneSubmissionReview.objects.exists())

    def test_stale_attempt_cannot_be_reviewed_and_form_is_only_on_latest(self):
        task = self.create_task()
        first = self.submit(task, name='first.pdf')
        first_review = review_capstone_submission(
            submission_attempt=first,
            reviewer=self.advisor,
            decision=CapstoneSubmissionReview.Decision.REVISION_REQUIRED,
            feedback='Yeni teslim gerekli.',
        )
        second = self.submit(task, name='second.pdf')
        first_review.delete()
        self.login()

        response = self.client.get(self.detail_url)
        self.assertNotContains(
            response,
            reverse('capstone:advisor_submission_review', args=[first.pk]),
        )
        self.assertContains(
            response,
            reverse('capstone:advisor_submission_review', args=[second.pk]),
        )

        response = self.client.post(
            reverse('capstone:advisor_submission_review', args=[first.pk]),
            {
                'decision': CapstoneSubmissionReview.Decision.ACCEPTED,
                'feedback': 'Eski teslim değerlendirmesi.',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            CapstoneSubmissionReview.objects.filter(submission_attempt=first).exists()
        )

    def test_already_reviewed_attempt_cannot_be_reviewed_again(self):
        task = self.create_task()
        attempt = self.submit(task)
        review = review_capstone_submission(
            submission_attempt=attempt,
            reviewer=self.advisor,
            decision=CapstoneSubmissionReview.Decision.REJECTED,
            feedback='İlk ve değişmez değerlendirme.',
        )
        self.login()

        response = self.client.post(
            reverse('capstone:advisor_submission_review', args=[attempt.pk]),
            {
                'decision': CapstoneSubmissionReview.Decision.ACCEPTED,
                'feedback': 'Üzerine yazma denemesi.',
            },
        )

        self.assertEqual(response.status_code, 200)
        review.refresh_from_db()
        self.assertEqual(review.decision, CapstoneSubmissionReview.Decision.REJECTED)
        self.assertEqual(CapstoneSubmissionReview.objects.filter(submission_attempt=attempt).count(), 1)


def attempt_name(payload):
    return str(payload['decision']).lower().replace('_', '-')
