from datetime import timedelta
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from projects.models import ProjectType
from core.models import AuditLog, Notification
from .academic_models import (CapstoneAcademicSubmission, CapstoneAcademicSubmissionFile, CapstoneHelpAttachment,
    CapstoneAdvisorPrivateNote, CapstoneHelpMessage, CapstoneLiteratureVersion,
    CapstoneMeetingNote, CapstonePlanCheckpoint)
from .academic_services import (academic_overview, archive_checkpoint, claim_student, initialize_project,
    add_expectation, add_private_note, change_advisor, checkpoint_state, create_help_request,
    decide_meeting, extend_deadline, record_meeting, reply_help_request, request_meeting,
    review_checkpoint, review_literature, save_plan_checkpoint, submit_checkpoint, help_state,
    tick_expectation, unassign_student, upload_literature)
from .models import (CapstoneEnrollment, CapstoneProject, CapstoneSubmissionAttempt,
    CapstoneSubmissionReview, CapstoneTask, CapstoneTerm)
from .services import approve_capstone_proposal, complete_capstone_project, submit_capstone_proposal
from .storage import PrivateFileSystemStorage


def user(username, role, level=None, staff=False):
    item = User.objects.create_user(username, password='pass', is_staff=staff)
    item.profile.user_type = role
    item.profile.class_level = level
    item.profile.save()
    return item


class AcademicV3Tests(TestCase):
    def setUp(self):
        self.private_directory = TemporaryDirectory()
        self.file_storages = []
        for model in (CapstoneAcademicSubmissionFile, CapstoneLiteratureVersion, CapstoneHelpAttachment):
            field = model._meta.get_field('file')
            self.file_storages.append((field, field.storage))
            field.storage = PrivateFileSystemStorage(location=self.private_directory.name)
        now = timezone.now()
        self.term = CapstoneTerm.objects.create(
            academic_year='2026-2027', semester='FALL', starts_at=now - timedelta(days=3),
            midterm_at=now + timedelta(days=30), final_at=now + timedelta(days=90), is_active=True)
        self.student = user('v3-student', 'student', '4')
        self.other = user('v3-other', 'student', '4')
        self.teacher = user('v3-teacher', 'teacher')
        self.other_teacher = user('v3-other-teacher', 'teacher')
        self.admin = user('v3-admin', 'teacher', staff=True)
        self.enrollment = CapstoneEnrollment.objects.create(term=self.term, student=self.student)
        CapstoneEnrollment.objects.create(term=self.term, student=self.other)
        ProjectType.objects.get_or_create(code='CAPSTONE', defaults={'name': 'Bitirme Projesi', 'slug': 'capstone'})

    def tearDown(self):
        for field, storage in self.file_storages:
            field.storage = storage
        self.private_directory.cleanup()
        super().tearDown()

    def create_project(self):
        claim_student(enrollment=self.enrollment, advisor=self.teacher)
        return initialize_project(enrollment=self.enrollment, student=self.student,
                                  title='Yeni Çalışma', description='Amaç')

    def test_claim_and_student_initialization(self):
        self.client.force_login(self.student)
        self.assertContains(self.client.get(reverse('capstone:student_home')), 'Danışman ataması bekleniyor')
        with self.assertRaises(PermissionDenied):
            claim_student(enrollment=self.enrollment, advisor=self.student)
        claim_student(enrollment=self.enrollment, advisor=self.teacher)
        self.assertTrue(Notification.objects.filter(recipient=self.student,
            title='Bitirme Projesi danışmanınız atandı.').exists())
        self.assertTrue(AuditLog.objects.filter(action='capstone.advisor_assigned',
            target_id=str(self.enrollment.pk)).exists())
        with self.assertRaises(ValidationError):
            claim_student(enrollment=self.enrollment, advisor=self.other_teacher)
        response = self.client.get(reverse('capstone:student_home'))
        self.assertContains(response, 'Proje Bilgilerini Tamamla')
        self.assertNotContains(response, 'Danışman seçin')
        self.client.post(reverse('capstone:student_start'),
                         {'title': 'Yeni Çalışma', 'description': 'Amaç', 'advisor': self.other_teacher.pk})
        project = CapstoneProject.objects.get()
        self.assertEqual(project.project.advisor, self.teacher)
        self.assertEqual(project.checkpoints.count(), 0)
        workspace = self.client.get(reverse('capstone:student_home'))
        self.assertContains(workspace, 'Kontrol Noktaları')
        self.assertNotContains(workspace, 'Akademik puan')
        self.client.post(reverse('capstone:student_start'), {'title': 'Kopya', 'description': 'Amaç'})
        self.assertEqual(CapstoneProject.objects.count(), 1)

    def test_shared_plan_submission_review_and_progress(self):
        project = self.create_project()
        plan = self.teacher.capstone_plans.get(term=self.term)
        checkpoint = save_plan_checkpoint(plan=plan, actor=self.teacher, title='Literatür Taraması',
            description='Rapor', order=1, due_at=timezone.now() + timedelta(days=5))
        self.assertEqual(academic_overview(project)['percent'], 0)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('capstone:advisor_project_detail', args=[project.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('capstone:checkpoint_submit', args=[project.pk, checkpoint.pk])).status_code, 404)
        with self.assertRaises(PermissionDenied):
            save_plan_checkpoint(plan=plan, actor=self.other_teacher, checkpoint=checkpoint,
                title='Erişim', description='', order=1, due_at=checkpoint.due_at)
        first = submit_checkpoint(project=project, checkpoint=checkpoint, student=self.student, note='İlk')
        self.assertEqual(first.attempt_number, 1)
        with self.assertRaises(ValidationError):
            submit_checkpoint(project=project, checkpoint=checkpoint, student=self.student, note='Kopya')
        with self.assertRaises(PermissionDenied):
            review_checkpoint(submission=first, actor=self.other_teacher, decision='APPROVED', feedback='')
        review_checkpoint(submission=first, actor=self.teacher, decision='REVISION_REQUIRED', feedback='Düzeltin')
        second = submit_checkpoint(project=project, checkpoint=checkpoint, student=self.student, note='Düzeltildi')
        self.assertEqual(second.attempt_number, 2)
        review_checkpoint(submission=second, actor=self.teacher, decision='APPROVED', feedback='Uygun')
        self.assertEqual(academic_overview(project)['percent'], 100)
        self.assertEqual(AuditLog.objects.filter(action='capstone.checkpoint_submitted').count(), 2)
        self.assertEqual(AuditLog.objects.filter(action='capstone.checkpoint_reviewed').count(), 2)
        self.client.force_login(self.student)
        self.assertContains(self.client.get(reverse('capstone:student_home')), 'Literatür Taraması')
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(reverse('capstone:advisor_project_detail', args=[project.pk])), 'Literatür Taraması')
        self.assertContains(self.client.get(reverse('capstone:advisor_home')), 'Yeni Çalışma')
        self.assertContains(self.client.get(reverse('capstone:plan_home')), 'Literatür Taraması')
        self.assertContains(self.client.get(reverse('capstone:progress_matrix')), 'Literatür Taraması')
        self.assertEqual(CapstoneAcademicSubmission.objects.count(), 2)
        with self.assertRaises(ValidationError):
            submit_checkpoint(project=project, checkpoint=checkpoint, student=self.student, note='Üçüncü')
        checkpoint.refresh_from_db()
        self.assertEqual(checkpoint, CapstonePlanCheckpoint.objects.get(pk=checkpoint.pk))

    def test_unassign_before_project_and_protect_after(self):
        claim_student(enrollment=self.enrollment, advisor=self.teacher)
        unassign_student(enrollment=self.enrollment, actor=self.teacher)
        self.enrollment.refresh_from_db()
        self.assertIsNone(self.enrollment.advisor_id)
        claim_student(enrollment=self.enrollment, advisor=self.teacher)
        self.create_project_after_claim()
        with self.assertRaises(ValidationError):
            unassign_student(enrollment=self.enrollment, actor=self.teacher)

    def create_project_after_claim(self):
        return initialize_project(enrollment=self.enrollment, student=self.student,
                                  title='Yeni Çalışma', description='Amaç')

    def test_teacher_label(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('capstone:advisor_home'))
        self.assertContains(response, 'Akademisyen Paneli')
        self.assertContains(response, 'Öğrenci Havuzu')
        self.assertContains(self.client.get(reverse('capstone:student_pool')), 'Danışmanlığıma Ekle')
        self.client.force_login(self.admin)
        admin_pool = self.client.get(reverse('capstone:student_pool'))
        self.assertNotContains(admin_pool, 'Danışmanlığıma Ekle')
        self.assertNotContains(admin_pool, f'<option value="{self.admin.pk}">')

    def test_admin_can_select_existing_plan_and_progress_matrix(self):
        project = self.create_project()
        plan = self.teacher.capstone_plans.get(term=self.term)
        save_plan_checkpoint(plan=plan, actor=self.teacher, title='Analiz',
            description='', order=1, due_at=timezone.now() + timedelta(days=2))
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('capstone:plan_home')), 'Analiz')
        self.assertContains(self.client.get(reverse('capstone:progress_matrix')), self.student.username)
        self.assertNotContains(self.client.get(reverse('capstone:progress_matrix') + '?advisor=bad'),
                               self.student.username)

    def test_private_submission_file_delivery(self):
        project = self.create_project()
        plan = self.teacher.capstone_plans.get(term=self.term)
        checkpoint = save_plan_checkpoint(plan=plan, actor=self.teacher, title='Rapor', description='',
            order=1, due_at=timezone.now() + timedelta(days=5))
        field = CapstoneAcademicSubmissionFile._meta.get_field('file')
        original_storage = field.storage
        with TemporaryDirectory() as private_directory:
            field.storage = PrivateFileSystemStorage(location=private_directory)
            try:
                upload = SimpleUploadedFile('../rapor.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf')
                submission = submit_checkpoint(project=project, checkpoint=checkpoint,
                    student=self.student, files=[upload])
                attachment = submission.files.get()
                self.assertNotIn('rapor', attachment.file.name)
                url = reverse('capstone:academic_file', args=['submission', attachment.pk])
                self.client.force_login(self.other)
                self.assertEqual(self.client.get(url).status_code, 404)
                self.client.force_login(self.other_teacher)
                self.assertEqual(self.client.get(url).status_code, 404)
                self.client.logout()
                self.assertEqual(self.client.get(url).status_code, 404)
                self.client.force_login(self.student)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
                self.assertIn('private', response['Cache-Control'])
                self.assertIn('attachment', response['Content-Disposition'])
                response.close()
                self.assertNotContains(self.client.get(reverse('capstone:student_home')), '/media/academic/')
            finally:
                field.storage = original_storage

    def test_shared_plan_checklist_and_individual_extension(self):
        project = self.create_project()
        plan = self.teacher.capstone_plans.get(term=self.term)
        checkpoint = save_plan_checkpoint(plan=plan, actor=self.teacher, title='Analiz', description='Beklenenler',
            order=1, due_at=timezone.now() + timedelta(days=3))
        item = add_expectation(checkpoint=checkpoint, actor=self.teacher, title='Analiz raporu', order=1)
        second_item = add_expectation(checkpoint=checkpoint, actor=self.teacher, title='Yöntemi açıklayın', order=2)
        second_enrollment = CapstoneEnrollment.objects.get(term=self.term, student=self.other)
        claim_student(enrollment=second_enrollment, advisor=self.teacher)
        second_project = initialize_project(enrollment=second_enrollment, student=self.other,
                                            title='İkinci Proje', description='Amaç')
        self.assertEqual(academic_overview(second_project)['total'], 1)
        tick_expectation(project=project, checkpoint=checkpoint, item=item, student=self.student, checked=True)
        self.assertEqual(checkpoint_state(project, checkpoint), 'IN_PROGRESS')
        tick_expectation(project=project, checkpoint=checkpoint, item=second_item, student=self.student, checked=True)
        self.assertEqual(checkpoint_state(project, checkpoint), 'AWAITING_SUBMISSION')
        self.assertEqual(academic_overview(project)['approved'], 0)
        extended = timezone.now() + timedelta(days=8)
        extend_deadline(project=project, checkpoint=checkpoint, actor=self.teacher,
                        due_at=extended, reason='Belgeli ek süre')
        self.assertEqual(academic_overview(project)['rows'][0]['due_at'], extended)
        self.assertEqual(academic_overview(second_project)['rows'][0]['due_at'], checkpoint.due_at)
        new_date = timezone.now() + timedelta(days=5)
        save_plan_checkpoint(plan=plan, actor=self.teacher, checkpoint=checkpoint,
                             title='Analiz', description='Beklenenler', order=1, due_at=new_date)
        self.assertEqual(academic_overview(second_project)['rows'][0]['due_at'], new_date)
        self.assertEqual(academic_overview(project)['rows'][0]['due_at'], extended)
        self.assertEqual(plan.definitions.count(), 1)

    def test_history_locks_checkpoint_definition_and_completion(self):
        project = self.create_project()
        plan = self.teacher.capstone_plans.get(term=self.term)
        checkpoint = save_plan_checkpoint(plan=plan, actor=self.teacher, title='Tasarım', description='Rapor',
            order=1, due_at=timezone.now() + timedelta(days=3))
        with self.assertRaises(ValidationError):
            from .services import complete_capstone_project
            complete_capstone_project(capstone_project=project, actor=self.teacher)
        submission = submit_checkpoint(project=project, checkpoint=checkpoint,
                                       student=self.student, note='Tasarım teslimi')
        with self.assertRaises(ValidationError):
            save_plan_checkpoint(plan=plan, actor=self.teacher, checkpoint=checkpoint,
                                 title='Başka ad', description='Rapor', order=1, due_at=checkpoint.due_at)
        review_checkpoint(submission=submission, actor=self.teacher, decision='APPROVED', feedback='Uygun')
        from .services import complete_capstone_project
        completed = complete_capstone_project(capstone_project=project, actor=self.teacher)
        self.assertIsNotNone(completed.completed_at)
        self.assertEqual(completed.project.development_status, 'completed')
        self.assertEqual(complete_capstone_project(capstone_project=project, actor=self.teacher).pk, project.pk)

    def test_literature_help_meeting_and_private_note(self):
        project = self.create_project()
        upload = SimpleUploadedFile('literatur.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf')
        version = upload_literature(project=project, student=self.student, upload=upload)
        self.assertEqual(version.version, 1)
        review_literature(version=version, actor=self.teacher, decision='REVISION_REQUIRED', feedback='Kaynakları genişletin.')
        upload = SimpleUploadedFile('literatur-yeni.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf')
        second = upload_literature(project=project, student=self.student, upload=upload)
        self.assertEqual(second.version, 2)
        self.assertEqual(CapstoneLiteratureVersion.objects.filter(capstone_project=project).count(), 2)
        help_item = create_help_request(project=project, student=self.student,
            subject='Yöntem', description='Bir sorum var.')
        reply_help_request(request_item=help_item, actor=self.teacher, content='Şu yöntemi deneyin.')
        self.assertEqual(CapstoneHelpMessage.objects.filter(request=help_item).count(), 1)
        self.assertEqual(help_state(help_item), 'Akademisyen Yanıtladı')
        reply_help_request(request_item=help_item, actor=self.admin, content='Bu öneriyi izleyin.')
        self.assertEqual(help_state(help_item), 'Akademisyen Yanıtladı')
        meeting = request_meeting(project=project, student=self.student, subject='Görüşme',
                                  description='Planı konuşalım.', availability_note='Salı öğleden sonra')
        scheduled = timezone.now() + timedelta(days=2)
        decide_meeting(meeting=meeting, actor=self.teacher, decision='schedule', scheduled_at=scheduled)
        record_meeting(meeting=meeting, actor=self.teacher, content='Yöntem konuşuldu.')
        self.assertEqual(CapstoneMeetingNote.objects.filter(meeting=meeting).count(), 1)
        add_private_note(project=project, actor=self.teacher, content='Özel takip notu')
        self.assertEqual(CapstoneAdvisorPrivateNote.objects.filter(capstone_project=project).count(), 1)
        self.client.force_login(self.student)
        student_home = self.client.get(reverse('capstone:student_home'))
        self.assertContains(student_home, 'Yöntem konuşuldu')
        self.assertLess(student_home.content.index('Şu yöntemi deneyin.'.encode()),
                        student_home.content.index('Bu öneriyi izleyin.'.encode()))
        self.assertContains(self.client.get(reverse('capstone:student_home')), 'Açık yardım talebi')
        self.assertNotContains(self.client.get(reverse('capstone:student_home')), 'Özel takip notu')
        self.client.force_login(self.teacher)
        advisor_home = self.client.get(reverse('capstone:advisor_home'))
        self.assertContains(advisor_home, 'Danışman İletişimi')
        self.assertContains(advisor_home, 'Görüşme Talepleri')
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.get(reverse('capstone:advisor_project_detail', args=[project.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('capstone:help_reply', args=[help_item.pk]), {'content': 'Erişim'}).status_code, 404)

    def test_admin_advisor_change_revokes_old_access(self):
        project = self.create_project()
        plan = self.teacher.capstone_plans.get(term=self.term)
        checkpoint = save_plan_checkpoint(plan=plan, actor=self.teacher, title='Eski plan çalışması',
            description='', order=1, due_at=timezone.now() + timedelta(days=3))
        submit_checkpoint(project=project, checkpoint=checkpoint, student=self.student, note='Eski teslim')
        change_advisor(enrollment=self.enrollment, new_advisor=self.other_teacher,
                       actor=self.admin, reason='Resmi danışman değişikliği')
        project.refresh_from_db()
        self.assertEqual(project.project.advisor_id, self.other_teacher.pk)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse('capstone:advisor_project_detail', args=[project.pk])).status_code, 404)
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.get(reverse('capstone:advisor_project_detail', args=[project.pk])).status_code, 200)
        self.assertContains(self.client.get(reverse('capstone:process_report', args=[project.pk])),
                            'Eski plan çalışması')

    def test_checkpoint_archive_preserves_used_history(self):
        project = self.create_project()
        plan = self.teacher.capstone_plans.get(term=self.term)
        unused = save_plan_checkpoint(plan=plan, actor=self.teacher, title='Silinebilir',
            description='', order=1, due_at=timezone.now() + timedelta(days=2))
        self.assertEqual(archive_checkpoint(checkpoint=unused, actor=self.teacher), 'capstone.checkpoint_deleted')
        self.assertFalse(CapstonePlanCheckpoint.objects.filter(pk=unused.pk).exists())
        used = save_plan_checkpoint(plan=plan, actor=self.teacher, title='Korunacak',
            description='', order=1, due_at=timezone.now() + timedelta(days=2))
        submit_checkpoint(project=project, checkpoint=used, student=self.student, note='Teslim')
        self.assertEqual(archive_checkpoint(checkpoint=used, actor=self.teacher), 'capstone.checkpoint_archived')
        used.refresh_from_db()
        self.assertFalse(used.is_active)
        self.assertEqual(CapstoneAcademicSubmission.objects.count(), 1)
        with self.assertRaises(ValidationError):
            save_plan_checkpoint(plan=plan, actor=self.teacher, checkpoint=used,
                title='Değiştirilemez', description='', order=1, due_at=used.due_at)
        with self.assertRaises(ValidationError):
            archive_checkpoint(checkpoint=used, actor=self.teacher)

    def test_progress_matrix_reuses_plan_queries_across_students(self):
        project = self.create_project()
        plan = self.teacher.capstone_plans.get(term=self.term)
        checkpoint = save_plan_checkpoint(plan=plan, actor=self.teacher, title='Analiz',
            description='', order=1, due_at=timezone.now() + timedelta(days=2))
        item = add_expectation(checkpoint=checkpoint, actor=self.teacher, title='Rapor', order=1)
        tick_expectation(project=project, checkpoint=checkpoint, item=item,
                         student=self.student, checked=True)
        self.client.force_login(self.teacher)
        url = reverse('capstone:progress_matrix')
        with CaptureQueriesContext(connection) as single_queries:
            self.client.get(url)
        for index in range(3):
            extra = user(f'matrix-student-{index}', 'student', '4')
            enrollment = CapstoneEnrollment.objects.create(term=self.term, student=extra)
            claim_student(enrollment=enrollment, advisor=self.teacher)
            extra_project = initialize_project(enrollment=enrollment, student=extra,
                title=f'Çalışma {index}', description='Amaç')
            tick_expectation(project=extra_project, checkpoint=checkpoint, item=item,
                             student=extra, checked=True)
        with CaptureQueriesContext(connection) as multiple_queries:
            response = self.client.get(url)
        self.assertContains(response, 'matrix-student-2')
        self.assertLessEqual(len(multiple_queries) - len(single_queries), 3)

    def test_plan_and_linked_request_forms(self):
        project = self.create_project()
        plan = self.teacher.capstone_plans.get(term=self.term)
        self.client.force_login(self.teacher)
        due = (timezone.now() + timedelta(days=4)).strftime('%Y-%m-%dT%H:%M')
        response = self.client.post(reverse('capstone:plan_checkpoint_create', args=[plan.pk]),
            {'title': 'Literatür', 'description': 'Rapor', 'order': 1, 'due_at': due})
        self.assertEqual(response.status_code, 302)
        checkpoint = CapstonePlanCheckpoint.objects.get(plan=plan)
        self.client.force_login(self.student)
        response = self.client.get(reverse('capstone:student_home'))
        self.assertContains(response, 'İlgili Kontrol Noktası')
        self.client.post(reverse('capstone:help_create', args=[project.pk]),
            {'subject': 'Kaynaklar', 'description': 'Yardım gerekir.', 'checkpoint': checkpoint.pk})
        self.assertEqual(project.help_requests.get().checkpoint_id, checkpoint.pk)
        add_expectation(checkpoint=checkpoint, actor=self.teacher, title='İlk rapor', order=1)
        with self.assertRaises(ValidationError):
            add_expectation(checkpoint=checkpoint, actor=self.teacher, title='Çakışan rapor', order=1)
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(reverse('capstone:plan_home')), 'value="2"')
        self.client.post(reverse('capstone:expectation_add', args=[checkpoint.pk]),
            {'title': 'Çakışan rapor', 'order': 1})
        self.assertEqual(checkpoint.expectations.count(), 1)

    def test_meeting_cancellation_requires_reason(self):
        project = self.create_project()
        meeting = request_meeting(project=project, student=self.student, subject='Plan',
            description='Görüşelim', availability_note='Salı')
        decide_meeting(meeting=meeting, actor=self.teacher, decision='schedule',
                       scheduled_at=timezone.now() + timedelta(days=2))
        with self.assertRaises(ValidationError):
            decide_meeting(meeting=meeting, actor=self.teacher, decision='cancel', note='')
        decide_meeting(meeting=meeting, actor=self.teacher, decision='cancel', note='Program değişti')
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, 'CANCELLED')

    def test_legacy_proposal_and_scoring_post_endpoints_are_read_only(self):
        proposal = submit_capstone_proposal(student=self.student, advisor=self.teacher,
            title='Eski teklif', term=self.term)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(reverse('capstone:advisor_proposal_decide', args=[proposal.pk]),
            {'decision': 'approve'}).status_code, 404)
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(reverse('capstone:student_proposal_withdraw', args=[proposal.pk])).status_code, 404)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, 'PENDING')
        project = approve_capstone_proposal(proposal=proposal, actor=self.teacher)
        checkpoint = project.checkpoints.first()
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(reverse('capstone:advisor_checkpoint_evaluate', args=[checkpoint.pk]),
            {'score': 25, 'feedback': 'Gizli puan'}).status_code, 404)
        self.assertFalse(checkpoint.__class__.objects.filter(pk=checkpoint.pk, evaluation__isnull=False).exists())

    def test_legacy_project_can_complete_without_new_scores(self):
        proposal = submit_capstone_proposal(student=self.student, advisor=self.teacher,
            title='Eski proje', term=self.term)
        project = approve_capstone_proposal(proposal=proposal, actor=self.teacher)
        for checkpoint in project.checkpoints.all():
            task = CapstoneTask.objects.create(capstone_project=project, checkpoint=checkpoint,
                created_by=self.teacher, title='Çalışma', instructions='Teslim edin', due_at=checkpoint.due_at)
            submission = CapstoneSubmissionAttempt.objects.create(task=task, submitted_by=self.student,
                                                                  attempt_number=1)
            CapstoneSubmissionReview.objects.create(submission_attempt=submission, reviewed_by=self.teacher,
                decision='ACCEPTED', feedback='Uygun')
        self.assertEqual(project.checkpoints.filter(evaluation__isnull=False).count(), 0)
        complete_capstone_project(capstone_project=project, actor=self.teacher)
        project.refresh_from_db()
        self.assertIsNotNone(project.completed_at)

    def test_admin_change_forms_cannot_bypass_assignment_or_completion(self):
        request = RequestFactory().get('/admin/')
        request.user = self.admin
        self.assertFalse(admin.site._registry[CapstoneEnrollment].has_change_permission(request, self.enrollment))
        project = self.create_project()
        self.assertFalse(admin.site._registry[CapstoneProject].has_change_permission(request, project))
