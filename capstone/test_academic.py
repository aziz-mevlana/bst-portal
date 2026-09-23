from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog, Notification
from projects.models import ProjectType
from .forms import CapstoneEvaluationForm, CapstoneTaskForm

from .models import (
    CapstoneCheckpoint, CapstoneCheckpointEvaluation, CapstoneEnrollment,
    CapstoneProject, CapstoneProposal, CapstoneSubmissionAttempt,
    CapstoneSubmissionReview, CapstoneTask, CapstoneTerm,
)
from .services import (
    approve_capstone_proposal, complete_capstone_project, evaluate_capstone_checkpoint,
    reject_capstone_proposal, submit_capstone_proposal, withdraw_capstone_proposal,
)
from .workflow import capstone_overview


def academic_user(username, role, class_level=None, staff=False):
    user = User.objects.create_user(username, password='password', is_staff=staff)
    user.profile.user_type = role
    user.profile.class_level = class_level
    user.profile.save()
    return user


class CapstoneAcademicTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.term = CapstoneTerm.objects.create(
            academic_year='2026-2027', semester='FALL', starts_at=now - timedelta(weeks=2),
            midterm_at=now + timedelta(weeks=6), final_at=now + timedelta(weeks=14), is_active=True,
        )
        self.student = academic_user('academic-student', 'student', '4')
        self.other_student = academic_user('academic-other', 'student', '4')
        self.advisor = academic_user('academic-advisor', 'teacher')
        self.other_teacher = academic_user('academic-unrelated', 'teacher')
        self.admin = academic_user('academic-admin', 'teacher', staff=True)
        CapstoneEnrollment.objects.create(term=self.term, student=self.student)
        CapstoneEnrollment.objects.create(term=self.term, student=self.other_student)
        ProjectType.objects.get_or_create(code='CAPSTONE', defaults={'name': 'Bitirme Projesi', 'slug': 'capstone'})

    def proposal(self):
        return submit_capstone_proposal(student=self.student, advisor=self.advisor, term=self.term,
                                        title='Akademik çalışma', description='Öneri')

    def project(self):
        return approve_capstone_proposal(proposal=self.proposal(), actor=self.advisor)

    def test_task_and_evaluation_forms_use_turkish_labels(self):
        task = CapstoneTaskForm()
        self.assertEqual([task.fields[name].label for name in task.fields],
                         ['Görev başlığı', 'Görev açıklaması', 'Gerekli dosya sayısı', 'Son teslim tarihi'])
        self.assertNotIn('checkpoint', task.fields)
        evaluation = CapstoneEvaluationForm()
        self.assertEqual([evaluation.fields[name].label for name in evaluation.fields],
                         ['Puan', 'Akademik geri bildirim'])

    def test_proposal_lifecycle_and_notifications(self):
        proposal = self.proposal()
        self.assertEqual(proposal.status, 'PENDING')
        self.assertFalse(CapstoneProject.objects.exists())
        self.assertTrue(Notification.objects.filter(recipient=self.advisor, dedupe_key=f'capstone-proposal-{proposal.pk}').exists())
        with self.assertRaises(ValidationError):
            self.proposal()
        with self.assertRaises(ValidationError):
            approve_capstone_proposal(proposal=proposal, actor=self.other_teacher)
        project = approve_capstone_proposal(proposal=proposal, actor=self.advisor)
        proposal.refresh_from_db()
        self.assertEqual(proposal.resulting_capstone_project_id, project.pk)
        self.assertEqual(project.checkpoints.count(), 4)
        self.assertEqual(sum(project.checkpoints.values_list('max_score', flat=True)), 100)
        self.assertEqual(project.project.approval_status, 'approved')
        self.assertTrue(Notification.objects.filter(recipient=self.student, dedupe_key=f'capstone-proposal-approved-{proposal.pk}').exists())
        self.assertTrue(AuditLog.objects.filter(action='capstone.proposal_approved', target_id=str(proposal.pk)).exists())
        with self.assertRaises(ValidationError):
            approve_capstone_proposal(proposal=proposal, actor=self.advisor)
        with self.assertRaises(ValidationError):
            self.proposal()

    def test_reject_resubmit_and_withdraw(self):
        proposal = self.proposal()
        with self.assertRaises(ValidationError):
            reject_capstone_proposal(proposal=proposal, actor=self.advisor, note=' ')
        reject_capstone_proposal(proposal=proposal, actor=self.advisor, note='Kapsamı daraltın.')
        self.assertEqual(proposal.pk, CapstoneProposal.objects.get(pk=proposal.pk).pk)
        next_proposal = self.proposal()
        with self.assertRaises(ValidationError):
            withdraw_capstone_proposal(proposal=next_proposal, student=self.other_student)
        withdraw_capstone_proposal(proposal=next_proposal, student=self.student)
        self.assertEqual(CapstoneProposal.objects.filter(student=self.student).count(), 2)
        self.assertTrue(AuditLog.objects.filter(action='capstone.proposal_withdrawn', target_id=str(next_proposal.pk)).exists())

    def test_proposal_endpoint_idor_and_role_revocation(self):
        proposal = self.proposal()
        url = reverse('capstone:advisor_proposal_decide', args=[proposal.pk])
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.post(url, {'decision': 'approve'}).status_code, 404)
        self.client.force_login(self.other_student)
        self.assertEqual(self.client.post(reverse('capstone:student_proposal_withdraw', args=[proposal.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('capstone:student_home')), proposal.title)
        self.advisor.profile.user_type = 'student'
        self.advisor.profile.class_level = '4'
        self.advisor.profile.save()
        self.client.force_login(self.advisor)
        self.assertEqual(self.client.post(url, {'decision': 'approve'}).status_code, 404)
        self.assertFalse(CapstoneProject.objects.exists())

    def _accepted_task(self, project, checkpoint):
        task = CapstoneTask.objects.create(capstone_project=project, checkpoint=checkpoint, created_by=self.advisor,
                                           title=f'Görev {checkpoint.pk}', instructions='Rapor', required_file_count=1,
                                           due_at=checkpoint.due_at)
        attempt = CapstoneSubmissionAttempt.objects.create(task=task, submitted_by=self.student, attempt_number=1)
        CapstoneSubmissionReview.objects.create(submission_attempt=attempt, reviewed_by=self.advisor,
                                                 decision='ACCEPTED', feedback='Uygun.')
        return task

    def test_scoring_completion_and_derived_timeline(self):
        project = self.project()
        checkpoints = list(project.checkpoints.order_by('due_at'))
        self.assertEqual(capstone_overview(project)['stage'], 'Fikir')
        with self.assertRaises(ValidationError):
            complete_capstone_project(capstone_project=project, actor=self.advisor)
        for checkpoint in checkpoints:
            self._accepted_task(project, checkpoint)
            with self.assertRaises(ValidationError):
                evaluate_capstone_checkpoint(checkpoint=checkpoint, actor=self.advisor,
                                             score=checkpoint.max_score + 1, feedback='Uygun')
            evaluation = evaluate_capstone_checkpoint(checkpoint=checkpoint, actor=self.advisor,
                                                       score=checkpoint.max_score, feedback='Akademik olarak yeterli.')
            with self.assertRaises(ValidationError):
                evaluation.save()
            with self.assertRaises(ValidationError):
                evaluate_capstone_checkpoint(checkpoint=checkpoint, actor=self.advisor, score=1, feedback='Tekrar')
        overview = capstone_overview(project)
        self.assertEqual((overview['score_earned'], overview['score_total_max']), (100, 100))
        self.assertTrue(overview['completion_ready'])
        with self.assertRaises(ValidationError):
            complete_capstone_project(capstone_project=project, actor=self.other_teacher)
        completed = complete_capstone_project(capstone_project=project, actor=self.advisor)
        self.assertIsNotNone(completed.completed_at)
        self.assertEqual(completed.completed_by, self.advisor)
        self.assertEqual(completed.project.development_status, 'completed')
        self.assertEqual(complete_capstone_project(capstone_project=project, actor=self.advisor).pk, project.pk)
        self.assertEqual(AuditLog.objects.filter(action='capstone.project_completed', target_id=str(project.pk)).count(), 1)

    def test_student_start_waits_for_advisor_and_admin_can_approve(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse('capstone:student_start'), {
            'title': 'Onaylı fikir', 'description': 'Açıklama', 'advisor': self.advisor.pk,
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CapstoneProject.objects.exists())
        proposal = CapstoneProposal.objects.get(student=self.student)
        self.assertContains(self.client.get(reverse('capstone:student_home')), 'Danışman onayı bekleniyor')
        self.client.force_login(self.admin)
        response = self.client.post(reverse('capstone:advisor_proposal_decide', args=[proposal.pk]), {'decision': 'approve'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CapstoneProject.objects.count(), 1)

    def test_advisor_proposals_are_paginated_without_hiding_queue_count(self):
        for index in range(21):
            student = User.objects.create(username=f'queue-student-{index}')
            student.profile.user_type = 'student'
            student.profile.class_level = '4'
            student.profile.save(update_fields=['user_type', 'class_level'])
            CapstoneEnrollment.objects.create(term=self.term, student=student)
            submit_capstone_proposal(student=student, advisor=self.advisor, term=self.term,
                                     title=f'Teklif {index:02d}')
        self.client.force_login(self.advisor)
        first = self.client.get(reverse('capstone:advisor_home'))
        second = self.client.get(reverse('capstone:advisor_home') + '?proposal_page=2')
        self.assertEqual(first.context['proposal_count'], 21)
        self.assertEqual(len(first.context['proposals']), 20)
        self.assertEqual(len(second.context['proposals']), 1)
        self.assertContains(second, 'Teklif 20')

    def test_evaluation_and_completion_post_cannot_be_bypassed(self):
        project = self.project()
        checkpoint = project.checkpoints.first()
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.post(reverse('capstone:advisor_checkpoint_evaluate', args=[checkpoint.pk]),
                                          {'score': 999, 'feedback': 'x'}).status_code, 404)
        self.assertEqual(self.client.post(reverse('capstone:advisor_project_complete', args=[project.pk])).status_code, 404)
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(reverse('capstone:advisor_project_complete', args=[project.pk])).status_code, 404)
        self.assertFalse(CapstoneCheckpointEvaluation.objects.exists())

    def test_advisor_reassignment_and_role_change_revoke_private_access(self):
        project = self.project()
        detail = reverse('capstone:advisor_project_detail', args=[project.pk])
        generic_detail = reverse('projects:project_detail', args=[project.project_id])
        self.client.force_login(self.advisor)
        self.assertEqual(self.client.get(detail).status_code, 200)
        project.project.advisor = self.other_teacher
        project.project.save(update_fields=['advisor'])
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertNotEqual(self.client.get(generic_detail).status_code, 200)
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.get(detail).status_code, 200)
        self.other_teacher.profile.user_type = 'student'
        self.other_teacher.profile.class_level = '4'
        self.other_teacher.profile.save()
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertNotEqual(self.client.get(generic_detail).status_code, 200)
