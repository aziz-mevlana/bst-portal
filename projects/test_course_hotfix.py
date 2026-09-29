from datetime import timedelta
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog, Notification
from .course_work_models import (CourseProjectAssignment, CourseProjectTeam, CourseProjectParticipation,
                                 CourseProjectWork, CourseAssignmentCheckpoint, CourseAssignmentExpectation)
from .course_work_services import (edit_assignment, cancel_assignment, reactivate_assignment, purge_assignment,
    delete_empty_assignment, create_work, create_team, join_team, join_assignment, override_team_member,
    save_checkpoint, add_expectation, rotate_invitation)
from .milestone_services import submit_milestone, review_milestone
from .models import (Project, ProjectMilestone, ProjectMilestoneSubmission, ProjectMilestoneReview,
                     ProjectMilestoneSubmissionFile, ProjectMilestoneSubmissionLink, ProjectRepository)
from . import test_course_workflow as fixtures
from .test_course_workflow import user


class CourseHotfixTests(TestCase):
    assignment = fixtures.CourseAssignmentWorkflowTests.assignment

    def setUp(self):
        fixtures.CourseAssignmentWorkflowTests.setUp(self)
        self.admin = user('hotfix-admin', 'teacher')
        self.admin.is_staff = True
        self.admin.save(update_fields=['is_staff'])

    def populated(self, group=False):
        assignment = self.assignment(**({'mode': 'GROUP', 'min_team_size': 2, 'max_team_size': 3} if group else {}))
        join_assignment(token=assignment.invitation_token, student=self.student)
        if group:
            team = create_team(assignment=assignment, student=self.student, name='Takım')
            join_assignment(token=assignment.invitation_token, student=self.second_student)
            join_team(assignment=assignment, student=self.second_student, team_id=team.pk)
        checkpoint = save_checkpoint(assignment=assignment, actor=self.teacher,
            values=dict(title='Analiz', description='Beklentiler', order=1,
                        due_at=timezone.now()+timedelta(days=5), is_active=True))
        add_expectation(checkpoint=checkpoint, actor=self.teacher, title='Rapor')
        work = create_work(assignment=assignment, student=self.student, title='Projem', idea='Fikir', repository_path='bst/test')
        return assignment, work, work.project.milestones.get()

    def cancel(self, assignment):
        return cancel_assignment(assignment=assignment, actor=self.teacher, reason='Ders takvimi değişti')[0]

    def test_owner_and_admin_edit_and_noop_no_spam(self):
        assignment = self.assignment()
        edit_assignment(assignment=assignment, actor=self.teacher, values={'topic': 'Yeni konu'})
        edit_assignment(assignment=assignment, actor=self.admin, values={'purpose': 'Yeni amaç'})
        count = AuditLog.objects.filter(action='course.assignment_updated').count()
        edit_assignment(assignment=assignment, actor=self.admin, values={'purpose': 'Yeni amaç'})
        self.assertEqual(AuditLog.objects.filter(action='course.assignment_updated').count(), count)
        assignment.refresh_from_db()
        self.assertEqual(assignment.topic, 'Yeni konu')
        self.assertEqual(assignment.purpose, 'Yeni amaç')

    def test_other_teacher_and_student_denied_all_management(self):
        assignment = self.assignment()
        for actor in (self.other_teacher, self.student):
            for operation in (
                lambda: edit_assignment(assignment=assignment, actor=actor, values={'topic': 'Sahte'}),
                lambda: cancel_assignment(assignment=assignment, actor=actor, reason='Sahte'),
                lambda: delete_empty_assignment(assignment=assignment, actor=actor, reason='Sahte'),
                lambda: purge_assignment(assignment=assignment, actor=actor, reason='Sahte'),
                lambda: reactivate_assignment(assignment=assignment, actor=actor, reason='Sahte'),
            ):
                with self.assertRaises(PermissionDenied): operation()
            self.client.force_login(actor)
            for url in (reverse('projects:course_assignment_edit', args=[assignment.pk]),
                        *[reverse('projects:course_assignment_action', args=[assignment.pk, action])
                          for action in ('cancel', 'delete', 'purge', 'reactivate')]):
                self.assertEqual(self.client.get(url).status_code, 404)
                self.assertEqual(self.client.post(url, {'confirm': 'yes', 'reason': 'Sahte', 'version': 0}).status_code, 404)

    def test_teacher_cannot_purge_or_reactivate(self):
        assignment = self.cancel(self.assignment())
        self.client.force_login(self.teacher)
        for action in ('purge', 'reactivate'):
            self.assertEqual(self.client.post(reverse('projects:course_assignment_action', args=[assignment.pk, action]),
                {'confirm': 'yes', 'reason': 'Gerekçe', 'version': assignment.lifecycle_version}).status_code, 404)
        with self.assertRaises(PermissionDenied):
            reactivate_assignment(assignment=assignment, actor=self.teacher, reason='Aç')
        with self.assertRaises(PermissionDenied):
            purge_assignment(assignment=assignment, actor=self.teacher, reason='Sil')

    def test_participation_blocks_type_and_scope_switch(self):
        assignment = self.assignment()
        join_assignment(token=assignment.invitation_token, student=self.student)
        with self.assertRaises(ValidationError):
            edit_assignment(assignment=assignment, actor=self.teacher,
                            values={'mode': 'GROUP', 'min_team_size': 2, 'max_team_size': 3})
        with self.assertRaises(ValidationError):
            edit_assignment(assignment=assignment, actor=self.admin, values={'course': self.course})

    def test_min_max_and_team_compatibility(self):
        assignment, work, _ = self.populated(group=True)
        for values in ({'min_team_size': 1}, {'max_team_size': 1}, {'min_team_size': 4},
                       {'min_team_size': 3, 'max_team_size': 4}):
            with self.assertRaises(ValidationError):
                edit_assignment(assignment=assignment, actor=self.teacher, values=values)
        edit_assignment(assignment=assignment, actor=self.teacher, values={'max_team_size': 2})
        edit_assignment(assignment=assignment, actor=self.teacher, values={'max_team_size': 4})
        self.assertEqual(work.team.participants.count(), 2)

    def test_edit_chronology_and_timezone(self):
        assignment = self.assignment()
        for values in ({'join_deadline': assignment.ends_at}, {'ends_at': assignment.starts_at},
                       {'starts_at': assignment.starts_at.replace(tzinfo=None)}):
            with self.assertRaises(ValidationError):
                edit_assignment(assignment=assignment, actor=self.teacher, values=values)

    def test_cancel_requires_reason_and_confirmation(self):
        assignment = self.assignment()
        with self.assertRaises(ValidationError):
            cancel_assignment(assignment=assignment, actor=self.teacher, reason=' ')
        self.client.force_login(self.teacher)
        url = reverse('projects:course_assignment_action', args=[assignment.pk, 'cancel'])
        self.assertContains(self.client.get(url), 'Bu işlemi onaylıyorum.')
        self.client.post(url, {'reason': 'Gerekçe', 'version': 0})
        assignment.refresh_from_db()
        self.assertTrue(assignment.is_active)
        self.client.post(url, {'reason': 'Gerekçe', 'version': 0, 'confirm': 'yes'})
        assignment.refresh_from_db()
        self.assertTrue(assignment.is_cancelled)
        self.assertEqual(assignment.cancelled_by, self.teacher)
        self.assertEqual(assignment.cancellation_reason, 'Gerekçe')

    def test_cancel_notifications_group_and_duplicate(self):
        assignment, work, _ = self.populated(group=True)
        self.cancel(assignment)
        again, changed = cancel_assignment(assignment=assignment, actor=self.teacher, reason='Yeniden')
        self.assertFalse(changed)
        notices = Notification.objects.filter(dedupe_key__startswith=f'course-assignment-cancelled-{assignment.pk}-')
        self.assertEqual(set(notices.values_list('recipient_id', flat=True)), {self.student.pk, self.second_student.pk})
        self.assertEqual(notices.count(), 2)
        self.assertIn(self.course.name, notices.first().message)
        self.assertIn(self.teacher.username, notices.first().message)
        self.assertIn('Ders takvimi değişti', notices.first().message)
        self.assertEqual(AuditLog.objects.filter(action='course.assignment_cancelled').count(), 1)

    def test_cancel_notifications_individual_even_opted_out(self):
        assignment, _, _ = self.populated()
        from accounts.models import CommunicationPreference
        preferences, _ = CommunicationPreference.objects.get_or_create(user=self.student)
        preferences.platform_notifications = False
        preferences.save()
        self.cancel(assignment)
        self.assertEqual(Notification.objects.filter(recipient=self.student,
            dedupe_key__startswith='course-assignment-cancelled-').count(), 1)

    def test_cancel_blocks_all_services_and_preserves_readonly_history(self):
        assignment, work, milestone = self.populated(group=True)
        submission = submit_milestone(milestone=milestone, actor=self.student, note='Eski teslim')
        review = review_milestone(submission=submission, actor=self.teacher, outcome='REVISION_REQUIRED', feedback='Düzelt')
        self.cancel(assignment)
        operations = (
            lambda: join_assignment(token=assignment.invitation_token, student=self.third_student),
            lambda: create_team(assignment=assignment, student=self.student, name='Yeni'),
            lambda: join_team(assignment=assignment, student=self.third_student, team_id=work.team_id),
            lambda: create_work(assignment=assignment, student=self.student, title='Yeni', idea='Yeni'),
            lambda: submit_milestone(milestone=milestone, actor=self.student, note='Revizyon'),
            lambda: review_milestone(submission=submission, actor=self.teacher, outcome='APPROVED'),
            lambda: override_team_member(assignment=assignment, actor=self.teacher, student_id=self.second_student.pk,
                                         team_id=None, reason='Çıkar'),
            lambda: save_checkpoint(assignment=assignment, actor=self.teacher,
                                   values=dict(title='Yeni', description='', order=2, due_at=assignment.ends_at, is_active=True)),
            lambda: add_expectation(checkpoint=milestone.assignment_checkpoint, actor=self.teacher, title='Yeni'),
            lambda: rotate_invitation(assignment=assignment, actor=self.teacher),
            lambda: edit_assignment(assignment=assignment, actor=self.teacher, values={'topic': 'Yeni'}),
        )
        for operation in operations:
            with self.assertRaises((ValidationError, PermissionDenied)): operation()
        for actor in (self.student, self.teacher, self.admin):
            self.client.force_login(actor)
            response = self.client.get(reverse('projects:course_work_detail', args=[work.pk]))
            self.assertContains(response, 'İptal Edildi')
            self.assertContains(response, 'Eski teslim')
            self.assertContains(response, 'Düzelt')
            self.assertContains(response, 'bst/test')
            self.assertNotContains(response, '>Teslim Et<')
            self.assertNotContains(response, '>Değerlendir<')
            self.assertNotContains(response, 'Proje deposunu yönet')
        self.assertEqual(ProjectMilestoneSubmission.objects.count(), 1)
        self.assertTrue(ProjectMilestoneReview.objects.filter(pk=review.pk).exists())

    def test_cancel_blocks_legacy_repository_and_generic_submit(self):
        assignment, work, milestone = self.populated()
        self.cancel(assignment)
        self.client.force_login(self.student)
        for url in (reverse('projects:project_repository_save', args=[work.project_id]),
                    reverse('projects:project_repository_delete', args=[work.project_id]),
                    reverse('projects:milestone_submit', args=[milestone.pk]),
                    reverse('projects:course_work_submit', args=[work.pk, milestone.pk])):
            self.assertIn(self.client.post(url, {'repository_path': 'evil/new'}).status_code, (403, 404))
        self.assertEqual(work.project.repository.repository_path, 'bst/test')

    def test_cancelled_ui_hides_mutation_links(self):
        assignment, work, _ = self.populated(group=True)
        self.cancel(assignment)
        self.client.force_login(self.teacher)
        for section in ('overview', 'participants', 'plan'):
            response = self.client.get(reverse('projects:course_assignment_detail', args=[assignment.pk]), {'section': section})
            self.assertContains(response, 'İptal Edildi')
            for text in ('Kontrol Noktası Oluştur', 'Takım üyeliğini değiştir', 'Bağlantıyı Yenile', 'Yeni beklenen'):
                self.assertNotContains(response, text)
            self.assertNotContains(response, '>Kalıcı Sil<')
            self.assertNotContains(response, '>Yeniden Aktifleştir<')
        self.client.force_login(self.student)
        self.assertContains(self.client.get(reverse('projects:course_my_assignments')), 'İptal Edildi')
        self.assertContains(self.client.get(reverse('projects:course_invitation', args=[assignment.invitation_token])), 'İptal Edildi')

    def test_empty_delete_and_history_blocks(self):
        assignment = self.assignment()
        pk = assignment.pk
        delete_empty_assignment(assignment=assignment, actor=self.teacher, reason='Taslak')
        self.assertFalse(CourseProjectAssignment.objects.filter(pk=pk).exists())
        assignment, _, _ = self.populated()
        with self.assertRaises(ValidationError):
            delete_empty_assignment(assignment=assignment, actor=self.teacher, reason='Sil')
        empty_with_plan = self.assignment()
        save_checkpoint(assignment=empty_with_plan, actor=self.teacher,
            values=dict(title='Plan', description='', order=1, due_at=empty_with_plan.ends_at, is_active=True))
        with self.assertRaises(ValidationError):
            delete_empty_assignment(assignment=empty_with_plan, actor=self.teacher, reason='Sil')

    def test_admin_reactivation_preserves_cancellation_and_expired_deadline(self):
        assignment, work, milestone = self.populated()
        assignment.join_deadline = timezone.now()-timedelta(days=1)
        assignment.save()
        assignment = self.cancel(assignment)
        previous = (assignment.cancelled_at, assignment.cancelled_by_id, assignment.cancellation_reason)
        with self.assertRaises(ValidationError):
            reactivate_assignment(assignment=assignment, actor=self.admin, reason=' ')
        active, changed = reactivate_assignment(assignment=assignment, actor=self.admin, reason='Devam')
        self.assertTrue(changed)
        self.assertTrue(active.is_active)
        self.assertEqual(previous, (active.cancelled_at, active.cancelled_by_id, active.cancellation_reason))
        with self.assertRaises(ValidationError):
            join_assignment(token=active.invitation_token, student=self.second_student)
        submit_milestone(milestone=milestone, actor=self.student, note='Devam')
        self.assertEqual(Notification.objects.filter(recipient=self.student,
            dedupe_key__startswith='course-assignment-reactivated-').count(), 1)
        with self.assertRaises(ValidationError):
            cancel_assignment(assignment=assignment, actor=self.teacher, reason='Eski form')
        self.assertEqual(AuditLog.objects.filter(action='course.assignment_cancelled').count(), 1)

    def test_admin_purge_graph_and_unrelated_preserved(self):
        assignment, work, milestone = self.populated(group=True)
        submission = submit_milestone(milestone=milestone, actor=self.student, links=['https://example.com'])
        review_milestone(submission=submission, actor=self.teacher, outcome='APPROVED')
        other, other_work, other_milestone = self.populated()
        snapshot = purge_assignment(assignment=assignment, actor=self.admin, reason='Test verisi')
        self.assertEqual(snapshot['participant_count'], 2)
        self.assertEqual(snapshot['team_count'], 1)
        for model, pk in ((CourseProjectAssignment, assignment.pk), (Project, work.project_id),
                          (ProjectMilestone, milestone.pk), (ProjectMilestoneSubmission, submission.pk)):
            self.assertFalse(model.objects.filter(pk=pk).exists())
        self.assertFalse(ProjectMilestoneReview.objects.filter(submission_id=submission.pk).exists())
        self.assertFalse(ProjectMilestoneSubmissionLink.objects.filter(submission_id=submission.pk).exists())
        self.assertFalse(CourseProjectTeam.objects.filter(assignment_id=assignment.pk).exists())
        self.assertFalse(CourseProjectParticipation.objects.filter(assignment_id=assignment.pk).exists())
        self.assertFalse(CourseAssignmentCheckpoint.objects.filter(assignment_id=assignment.pk).exists())
        self.assertFalse(CourseAssignmentExpectation.objects.filter(checkpoint=milestone.assignment_checkpoint_id).exists())
        self.assertFalse(ProjectRepository.objects.filter(project_id=work.project_id).exists())
        self.assertTrue(CourseProjectAssignment.objects.filter(pk=other.pk).exists())
        self.assertTrue(Project.objects.filter(pk=other_work.project_id).exists())
        audit = AuditLog.objects.get(action='course.assignment_purged')
        self.assertEqual(audit.actor, self.admin)
        self.assertEqual(audit.metadata['reason'], 'Test verisi')
        self.assertEqual(audit.target_id, str(assignment.pk))
        self.assertFalse(Notification.objects.filter(target_url=reverse('projects:course_work_detail', args=[work.pk])).exists())

    def test_purge_confirmation_and_reason_required(self):
        assignment = self.assignment()
        self.client.force_login(self.admin)
        url = reverse('projects:course_assignment_action', args=[assignment.pk, 'purge'])
        for values in ({'reason': 'Sil', 'confirm': 'yes'},
                       {'reason': '', 'confirm': 'yes', 'confirmation': 'KALICI OLARAK SİL'}):
            self.assertEqual(self.client.post(url, values).status_code, 200)
            self.assertTrue(CourseProjectAssignment.objects.filter(pk=assignment.pk).exists())
        response = self.client.post(url, {'reason': 'Sil', 'confirm': 'yes', 'confirmation': 'KALICI OLARAK SİL'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CourseProjectAssignment.objects.filter(pk=assignment.pk).exists())

    def test_purge_files_on_commit_shared_names_and_cleanup_exception(self):
        from .storage import ProjectMilestonePrivateStorage
        with TemporaryDirectory() as directory, patch.object(
                ProjectMilestoneSubmissionFile._meta.get_field('file'), 'storage',
                ProjectMilestonePrivateStorage(location=directory)):
            assignment, work, milestone = self.populated()
            submission = submit_milestone(milestone=milestone, actor=self.student,
                                         files=[SimpleUploadedFile('report.pdf', b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF', content_type='application/pdf')])
            file = submission.files.get().file
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                purge_assignment(assignment=assignment, actor=self.admin, reason='Sil')
            self.assertTrue(file.storage.exists(file.name))
            self.assertEqual(len(callbacks), 1)
            callbacks[0]()
            self.assertFalse(file.storage.exists(file.name))
            assignment, work, milestone = self.populated()
            submission = submit_milestone(milestone=milestone, actor=self.student,
                                         files=[SimpleUploadedFile('keep.pdf', b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF', content_type='application/pdf')])
            file = submission.files.get().file
            other, _, other_milestone = self.populated()
            other_submission = submit_milestone(milestone=other_milestone, actor=self.student,
                files=[SimpleUploadedFile('other.pdf', b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF', content_type='application/pdf')])
            ProjectMilestoneSubmissionFile.objects.filter(submission=other_submission).update(file=file.name)
            with self.captureOnCommitCallbacks(execute=True):
                purge_assignment(assignment=assignment, actor=self.admin, reason='Sil')
            self.assertTrue(file.storage.exists(file.name))
            self.client.force_login(self.admin)
            with patch.object(file.storage, 'delete', side_effect=OSError('storage down')):
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(reverse('projects:course_assignment_action', args=[other.pk, 'purge']),
                        {'confirm': 'yes', 'confirmation': 'KALICI OLARAK SİL', 'reason': 'Sil'})
            self.assertEqual(response.status_code, 302)
            self.assertFalse(CourseProjectAssignment.objects.filter(pk=other.pk).exists())

    def test_owner_and_admin_edit_ui(self):
        assignment, _, _ = self.populated()
        for actor in (self.teacher, self.admin):
            self.client.force_login(actor)
            url = reverse('projects:course_assignment_edit', args=[assignment.pk])
            self.assertContains(self.client.get(url), 'Değişiklikleri Kaydet')
            values = {**self.values, 'course': self.course.pk, 'topic': 'UI konusu',
                      'join_deadline': assignment.join_deadline.strftime('%Y-%m-%dT%H:%M%z'),
                      'starts_at': assignment.starts_at.strftime('%Y-%m-%dT%H:%M%z'),
                      'ends_at': assignment.ends_at.strftime('%Y-%m-%dT%H:%M%z')}
            values.pop('min_team_size'); values.pop('max_team_size')
            self.assertEqual(self.client.post(url, values).status_code, 302)
        assignment.refresh_from_db()
        self.assertEqual(assignment.topic, 'UI konusu')

    def test_teacher_populated_delete_post_blocked_and_forged_assignment(self):
        assignment, work, _ = self.populated()
        self.client.force_login(self.teacher)
        response = self.client.post(reverse('projects:course_assignment_action', args=[assignment.pk, 'delete']),
                                    {'confirm': 'yes', 'reason': 'Sil'})
        self.assertContains(response, 'İptal Et')
        self.assertTrue(Project.objects.filter(pk=work.project_id).exists())
        self.assertTrue(CourseProjectAssignment.objects.filter(pk=assignment.pk).exists())
        self.assertEqual(self.client.post(reverse('projects:course_assignment_edit', args=[999999])).status_code, 404)
        self.assertEqual(self.client.post(reverse('projects:course_assignment_action', args=[999999, 'cancel']),
            {'confirm': 'yes', 'reason': 'Sahte', 'version': 0}).status_code, 404)

    def test_max_below_largest_team_and_edit_notifies_once_per_student(self):
        assignment, work, _ = self.populated(group=True)
        join_assignment(token=assignment.invitation_token, student=self.third_student)
        join_team(assignment=assignment, student=self.third_student, team_id=work.team_id)
        with self.assertRaises(ValidationError):
            edit_assignment(assignment=assignment, actor=self.teacher, values={'max_team_size': 2})
        edit_assignment(assignment=assignment, actor=self.teacher, values={'ends_at': assignment.ends_at+timedelta(days=1)})
        self.assertEqual(Notification.objects.filter(dedupe_key__startswith='course-assignment-edited-').count(), 3)
        # A repeat with identical values creates neither audit nor notifications.
        edit_assignment(assignment=assignment, actor=self.teacher, values={'ends_at': assignment.ends_at+timedelta(days=1)})
        self.assertEqual(Notification.objects.filter(dedupe_key__startswith='course-assignment-edited-').count(), 3)

    def test_purge_rollback_preserves_history_and_no_file_cleanup(self):
        from django.db import transaction
        assignment, work, milestone = self.populated()
        submission = submit_milestone(milestone=milestone, actor=self.student)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    purge_assignment(assignment=assignment, actor=self.admin, reason='Sil')
                    raise RuntimeError('rollback')
        self.assertEqual(callbacks, [])
        self.assertTrue(CourseProjectAssignment.objects.filter(pk=assignment.pk).exists())
        self.assertTrue(Project.objects.filter(pk=work.project_id).exists())
        self.assertTrue(ProjectMilestoneSubmission.objects.filter(pk=submission.pk).exists())
        self.assertFalse(AuditLog.objects.filter(action='course.assignment_purged').exists())

    def test_cancelled_file_history_accessible_with_idor_denied(self):
        from .storage import ProjectMilestonePrivateStorage
        with TemporaryDirectory() as directory, patch.object(ProjectMilestoneSubmissionFile._meta.get_field('file'),
                'storage', ProjectMilestonePrivateStorage(location=directory)):
            assignment, work, milestone = self.populated()
            submission = submit_milestone(milestone=milestone, actor=self.student,
                files=[SimpleUploadedFile('report.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf')])
            self.cancel(assignment)
            url = reverse('projects:milestone_file', args=[submission.files.get().pk])
            for actor in (self.student, self.teacher, self.admin):
                self.client.force_login(actor)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn('attachment', response['Content-Disposition'])
                self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))
            for actor in (self.other_teacher, self.second_student):
                self.client.force_login(actor)
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_cancelled_invite_without_work_has_no_initialization_cta(self):
        assignment = self.assignment()
        join_assignment(token=assignment.invitation_token, student=self.student)
        self.cancel(assignment)
        self.client.force_login(self.student)
        response = self.client.get(reverse('projects:course_invitation', args=[assignment.invitation_token]))
        self.assertContains(response, 'İptal Edildi')
        self.assertNotContains(response, '>Projeyi Oluştur<')
        self.assertNotContains(response, '>Projeye Katıl<')

    def test_admin_reactivate_post_and_duplicate_notification(self):
        assignment, _, _ = self.populated()
        assignment = self.cancel(assignment)
        self.client.force_login(self.admin)
        url = reverse('projects:course_assignment_action', args=[assignment.pk, 'reactivate'])
        self.assertContains(self.client.get(url), 'Yeniden Aktifleştir')
        self.assertEqual(self.client.post(url, {'confirm': 'yes', 'reason': '', 'version': assignment.lifecycle_version}).status_code, 200)
        values = {'confirm': 'yes', 'reason': 'Ders devam ediyor', 'version': assignment.lifecycle_version}
        self.assertEqual(self.client.post(url, values).status_code, 302)
        self.assertEqual(self.client.post(url, values).status_code, 302)
        self.assertEqual(AuditLog.objects.filter(action='course.assignment_reactivated').count(), 1)
        self.assertEqual(Notification.objects.filter(dedupe_key__startswith='course-assignment-reactivated-').count(), 1)

    def test_cancelled_history_includes_archived_checkpoints(self):
        assignment, work, milestone = self.populated()
        submit_milestone(milestone=milestone, actor=self.student, note='Arşivlenmiş teslim')
        definition = milestone.assignment_checkpoint
        save_checkpoint(assignment=assignment, actor=self.teacher, checkpoint=definition,
            values=dict(title=definition.title, description=definition.description, order=definition.order,
                        due_at=definition.due_at, is_active=False))
        self.cancel(assignment)
        self.client.force_login(self.student)
        response = self.client.get(reverse('projects:course_work_detail', args=[work.pk]))
        self.assertContains(response, 'Arşivlenmiş teslim')
        self.assertNotContains(response, '>Teslim Et<')

    def test_deleted_during_cancel_returns_404_instead_of_refresh_500(self):
        assignment = self.assignment()
        self.client.force_login(self.teacher)
        def delete_then_reject(**kwargs):
            CourseProjectAssignment.objects.filter(pk=assignment.pk).delete()
            raise ValidationError('Çalışma kalıcı olarak silindi.')
        with patch('projects.course_work_services.cancel_assignment', side_effect=delete_then_reject):
            response = self.client.post(reverse('projects:course_assignment_action', args=[assignment.pk, 'cancel']),
                {'confirm': 'yes', 'reason': 'İptal', 'version': 0})
        self.assertEqual(response.status_code, 404)

    def test_cancellation_notification_keeps_reason_with_long_labels(self):
        assignment, _, _ = self.populated()
        self.course.name = 'Ders ' + 'uzun ' * 35
        self.course.save()
        self.teacher.first_name = 'Akademisyen ' + 'A' * 120
        self.teacher.last_name = 'B' * 120
        self.teacher.save()
        cancel_assignment(assignment=assignment, actor=self.teacher, reason='Takvim değişti')
        notice = Notification.objects.get(dedupe_key__startswith='course-assignment-cancelled-')
        self.assertIn('Takvim değişti', notice.message)
        self.assertIn(self.course.code, notice.message)
        self.assertIn('Akademisyen', notice.message)
        self.assertLessEqual(len(notice.message), 300)

    def test_academic_audit_history_blocks_teacher_empty_delete(self):
        assignment = self.assignment()
        checkpoint = save_checkpoint(assignment=assignment, actor=self.teacher,
            values=dict(title='Plan', description='', order=1, due_at=assignment.ends_at, is_active=True))
        # Simulate an old/admin correction removing the row while its academic audit remains.
        checkpoint.delete()
        with self.assertRaises(ValidationError):
            delete_empty_assignment(assignment=assignment, actor=self.teacher, reason='Sil')
        self.assertTrue(CourseProjectAssignment.objects.filter(pk=assignment.pk).exists())

    def test_cancelled_routes_reject_all_academic_mutations(self):
        assignment, work, milestone = self.populated(group=True)
        submission = submit_milestone(milestone=milestone, actor=self.student)
        review_milestone(submission=submission, actor=self.teacher, outcome='REVISION_REQUIRED', feedback='Düzelt')
        before = (assignment.participants.count(), assignment.teams.count(), assignment.works.count(),
                  assignment.checkpoints.count(), ProjectMilestoneSubmission.objects.count(),
                  ProjectMilestoneReview.objects.count())
        self.cancel(assignment)
        self.client.force_login(self.student)
        student_routes = (
            ('course_invitation', [assignment.invitation_token], {}),
            ('course_team_create', [assignment.pk], {'name': 'Yeni'}),
            ('course_team_join', [assignment.pk, work.team_id], {}),
            ('course_work_create', [assignment.pk], {'title': 'Yeni', 'idea': 'Yeni'}),
            ('course_work_submit', [work.pk, milestone.pk], {'completion_note': 'Revizyon'}),
            ('milestone_submit', [milestone.pk], {'completion_note': 'Revizyon'}),
            ('project_update', [work.project_id], {'title': 'Yeni', 'description': 'Yeni'}),
            ('project_repository_save', [work.project_id], {'repository_path': 'bst/changed'}),
            ('project_repository_delete', [work.project_id], {}),
            ('project_showcase_manage', [work.project_id], {}),
            ('complete_project', [work.project_id], {}),
            ('change_project_status', [work.project_id], {'status': 'completed'}),
        )
        for name, args, data in student_routes:
            with self.subTest(route=name):
                self.assertIn(self.client.post(reverse('projects:'+name, args=args), data).status_code, (302, 403, 404))
        self.client.force_login(self.teacher)
        for name, args, data in (
            ('course_team_override', [assignment.pk, self.second_student.pk], {'team_id': '', 'reason': 'Çıkar'}),
            ('course_checkpoint_create', [assignment.pk], {'title': 'Yeni', 'description': '', 'order': 2,
                'due_at': assignment.ends_at.isoformat(), 'is_active': 'on'}),
            ('course_checkpoint_edit', [assignment.pk, milestone.assignment_checkpoint_id],
                {'title': 'Analiz', 'description': 'Beklentiler', 'order': 1,
                 'due_at': assignment.ends_at.isoformat(), 'is_active': 'on'}),
            ('course_expectation_add', [milestone.assignment_checkpoint_id], {'title': 'Yeni'}),
            ('course_work_review', [work.pk, submission.pk], {'outcome': 'APPROVED'}),
            ('milestone_review', [submission.pk], {'outcome': 'REVISION_REQUIRED', 'feedback': 'Yeni'}),
            ('course_invitation_update', [assignment.pk], {'action': 'enable'}),
            ('approve_project', [work.project_id], {}),
            ('start_project', [work.project_id], {}),
        ):
            with self.subTest(route=name):
                self.assertIn(self.client.post(reverse('projects:'+name, args=args), data).status_code, (200, 302, 403, 404))
        after = (assignment.participants.count(), assignment.teams.count(), assignment.works.count(),
                 assignment.checkpoints.count(), ProjectMilestoneSubmission.objects.count(),
                 ProjectMilestoneReview.objects.count())
        self.assertEqual(before, after)
        work.project.refresh_from_db()
        self.assertEqual(work.project.title, 'Projem')
        self.assertEqual(work.project.development_status, 'in_progress')
        self.assertEqual(work.project.repository.repository_path, 'bst/test')
        self.assertEqual(milestone.assignment_checkpoint.expected_items.count(), 1)

    def test_management_get_is_readonly_and_post_requires_csrf(self):
        from django.test import Client
        assignment = self.assignment()
        for actor in (self.teacher, self.admin):
            self.client.force_login(actor)
            count = AuditLog.objects.count()
            for action in ('cancel', 'delete', 'purge', 'reactivate'):
                response = self.client.get(reverse('projects:course_assignment_action', args=[assignment.pk, action]))
                self.assertIn(response.status_code, (200, 404))
            self.assertEqual(AuditLog.objects.count(), count)
            self.assertTrue(CourseProjectAssignment.objects.filter(pk=assignment.pk, is_active=True).exists())
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        for action in ('cancel', 'delete', 'purge', 'reactivate'):
            self.assertEqual(client.post(reverse('projects:course_assignment_action', args=[assignment.pk, action]),
                {'confirm': 'yes', 'reason': 'Sahte', 'version': 0}).status_code, 403)
        self.assertEqual(client.post(reverse('projects:course_assignment_edit', args=[assignment.pk]), {}).status_code, 403)

    def test_cancel_rollback_does_not_leave_audit_or_notifications(self):
        from django.db import transaction
        assignment, _, _ = self.populated(group=True)
        with self.assertRaises(RuntimeError), transaction.atomic():
            self.cancel(assignment)
            raise RuntimeError('rollback')
        assignment.refresh_from_db()
        self.assertTrue(assignment.is_active)
        self.assertIsNone(assignment.cancelled_at)
        self.assertFalse(AuditLog.objects.filter(action='course.assignment_cancelled').exists())
        self.assertFalse(Notification.objects.filter(dedupe_key__startswith='course-assignment-cancelled-').exists())

    def test_cancel_notifications_do_not_read_preferences_per_participant(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        assignment, _, _ = self.populated(group=True)
        with CaptureQueriesContext(connection) as queries:
            self.cancel(assignment)
        preference_reads = [row for row in queries if 'FROM "accounts_communicationpreference"' in row['sql']]
        self.assertLessEqual(len(preference_reads), 1)

    def test_non_ascii_numeric_form_ids_are_rejected_safely(self):
        assignment = self.assignment(mode='GROUP', min_team_size=2, max_team_size=3)
        join_assignment(token=assignment.invitation_token, student=self.student)
        self.client.force_login(self.teacher)
        response = self.client.post(reverse('projects:course_assignment_action', args=[assignment.pk, 'cancel']),
            {'confirm': 'yes', 'reason': 'İptal', 'version': '²'})
        self.assertEqual(response.status_code, 200)
        assignment.refresh_from_db()
        self.assertTrue(assignment.is_active)
        for invalid in ('²', '9' * 5000):
            self.assertEqual(self.client.post(reverse('projects:course_team_override', args=[assignment.pk, self.student.pk]),
                {'team_id': invalid, 'reason': 'Değiştir'}).status_code, 404)

    def test_purge_removes_extended_project_graph_and_preserves_user_course_and_portfolio(self):
        from .models import (ProjectCaseStudy, ProjectWritingSuggestion, ProjectContribution,
                             ProjectAchievement, ProjectUpdate, ProjectComment, CourseInstructor)
        assignment, work, _ = self.populated()
        related = [
            ProjectCaseStudy.objects.create(project=work.project, summary='Geçmiş'),
            ProjectWritingSuggestion.objects.create(project=work.project, created_by=self.student, original_text='Geçmiş'),
            ProjectContribution.objects.create(project=work.project, user=self.student, role='Yazar', contribution_description='Geçmiş'),
            ProjectAchievement.objects.create(project=work.project, title='Başarı', achievement_type='other'),
            ProjectUpdate.objects.create(project=work.project, title='Güncelleme', description='Geçmiş', created_by=self.student),
            ProjectComment.objects.create(project=work.project, author=self.student, content='Geçmiş'),
        ]
        portfolio = Project.objects.create(project_type=work.project.project_type, course=self.course,
            title='Portföy', created_by=self.student)
        unrelated = ProjectUpdate.objects.create(project=portfolio, description='Korunacak', created_by=self.student)
        purge_assignment(assignment=assignment, actor=self.admin, reason='Test graph')
        for obj in related:
            self.assertFalse(type(obj).objects.filter(pk=obj.pk).exists())
        self.assertTrue(Project.objects.filter(pk=portfolio.pk).exists())
        self.assertTrue(ProjectUpdate.objects.filter(pk=unrelated.pk).exists())
        self.assertTrue(type(self.course).objects.filter(pk=self.course.pk).exists())
        self.assertTrue(CourseInstructor.objects.filter(course=self.course, instructor=self.teacher).exists())
        self.assertTrue(type(self.student).objects.filter(pk=self.student.pk).exists())
        self.assertTrue(type(self.student.profile).objects.filter(pk=self.student.profile.pk).exists())

    def test_file_cleanup_continues_after_one_exception_and_rollback_keeps_file(self):
        from .storage import ProjectMilestonePrivateStorage
        from django.db import transaction
        with TemporaryDirectory() as directory, patch.object(ProjectMilestoneSubmissionFile._meta.get_field('file'),
                'storage', ProjectMilestonePrivateStorage(location=directory)):
            assignment, _, milestone = self.populated()
            submission = submit_milestone(milestone=milestone, actor=self.student, files=[
                SimpleUploadedFile('one.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf'),
                SimpleUploadedFile('two.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf')])
            files = [row.file for row in submission.files.order_by('pk')]
            with self.assertRaises(RuntimeError), transaction.atomic():
                purge_assignment(assignment=assignment, actor=self.admin, reason='Sil')
                raise RuntimeError('rollback')
            self.assertTrue(all(file.storage.exists(file.name) for file in files))
            original_delete = files[0].storage.delete
            def fail_first(name):
                if name == files[0].name:
                    raise OSError('first failed')
                original_delete(name)
            with patch.object(files[0].storage, 'delete', side_effect=fail_first):
                with self.assertLogs('projects.course_work_services', level='ERROR'):
                    with self.captureOnCommitCallbacks(execute=True):
                        purge_assignment(assignment=assignment, actor=self.admin, reason='Sil')
            self.assertTrue(files[0].storage.exists(files[0].name))
            self.assertFalse(files[1].storage.exists(files[1].name))

    def test_owner_scope_still_denies_another_instructor_of_same_course(self):
        from .models import CourseInstructor
        CourseInstructor.objects.create(course=self.course, instructor=self.other_teacher)
        assignment = self.assignment()
        self.client.force_login(self.other_teacher)
        for action in ('cancel', 'delete', 'purge', 'reactivate'):
            self.assertEqual(self.client.post(reverse('projects:course_assignment_action', args=[assignment.pk, action]),
                {'confirm': 'yes', 'reason': 'Başka çalışma', 'version': 0}).status_code, 404)
        self.assertEqual(self.client.get(reverse('projects:course_assignment_edit', args=[assignment.pk])).status_code, 404)
        for actor in (self.admin, self.teacher, self.student):
            self.client.force_login(actor)
            url = reverse('projects:course_assignment_edit', args=[assignment.pk]).replace(
                f'/{assignment.pk}/', '/11111111-1111-1111-1111-111111111111/')
            self.assertEqual(self.client.post(url).status_code, 404)

    def test_edit_exact_date_boundaries_and_join_deadline(self):
        assignment = self.assignment()
        edit_assignment(assignment=assignment, actor=self.teacher, values={'join_deadline': assignment.starts_at})
        with self.assertRaises(ValidationError):
            edit_assignment(assignment=assignment, actor=self.teacher, values={'ends_at': assignment.starts_at})
        assignment.refresh_from_db()
        with patch('projects.course_work_services.timezone.now', return_value=assignment.join_deadline):
            join_assignment(token=assignment.invitation_token, student=self.student)
        with patch('projects.course_work_services.timezone.now', return_value=assignment.join_deadline+timedelta(microseconds=1)):
            with self.assertRaises(ValidationError):
                join_assignment(token=assignment.invitation_token, student=self.second_student)

    def test_file_cleanup_rejects_traversal_without_deleting_unrelated_file(self):
        from pathlib import Path
        from .storage import ProjectMilestonePrivateStorage
        with TemporaryDirectory() as directory:
            unrelated = Path(directory) / 'outside.pdf'
            unrelated.write_bytes(b'unrelated')
            storage = ProjectMilestonePrivateStorage(location=str(Path(directory) / 'inside'))
            with patch.object(ProjectMilestoneSubmissionFile._meta.get_field('file'), 'storage', storage):
                assignment, _, milestone = self.populated()
                submission = submit_milestone(milestone=milestone, actor=self.student,
                    files=[SimpleUploadedFile('report.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf')])
                ProjectMilestoneSubmissionFile.objects.filter(submission=submission).update(file='../outside.pdf')
                with self.assertLogs('projects.course_work_services', level='ERROR'):
                    with self.captureOnCommitCallbacks(execute=True):
                        purge_assignment(assignment=assignment, actor=self.admin, reason='Sil')
                self.assertEqual(unrelated.read_bytes(), b'unrelated')
                self.assertFalse(CourseProjectAssignment.objects.filter(pk=assignment.pk).exists())

    def test_workspace_expectations_are_prefetched(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        assignment, work, _ = self.populated()
        checkpoint = save_checkpoint(assignment=assignment, actor=self.teacher,
            values=dict(title='İkinci', description='', order=2, due_at=assignment.ends_at, is_active=True))
        add_expectation(checkpoint=checkpoint, actor=self.teacher, title='İkinci rapor')
        self.cancel(assignment)
        self.client.force_login(self.student)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('projects:course_work_detail', args=[work.pk]))
        self.assertContains(response, 'İkinci rapor')
        expectation_reads = [row for row in queries if 'FROM "projects_courseassignmentexpectation"' in row['sql']]
        self.assertEqual(len(expectation_reads), 1)
