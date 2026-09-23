import tempfile
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from core.models import AuditLog, Notification

from .forms import ProjectForm, ProjectMilestoneForm, RequestForm
from .milestone_policies import can_manage_project_milestones, can_submit_project_milestone
from .milestone_services import review_milestone, save_milestone, submit_milestone
from .models import (
    Course, CourseInstructor, Project, ProjectMilestone,
    ProjectMilestoneReview, ProjectMilestoneSubmission, ProjectRequest,
    ProjectRequestApplication, ProjectType,
)
from .services import accept_project_request_application


def user_with_role(username, role='student', *, staff=False):
    user = User.objects.create_user(username, password='password', is_staff=staff)
    user.profile.user_type = role
    user.profile.class_level = '2' if role == 'student' else None
    user.profile.save()
    return user


class CourseInvariantTests(TestCase):
    def setUp(self):
        self.student = user_with_role('course-student')
        self.teacher = user_with_role('course-teacher', 'teacher')
        self.course_type = ProjectType.objects.get(code='COURSE')
        self.normal_type = ProjectType.objects.get(code='RESEARCH')
        self.course = Course.objects.create(name='Software Engineering')

    def test_project_and_request_require_course_and_reject_injected_course(self):
        with self.assertRaises(ValidationError):
            Project.objects.create(project_type=self.course_type, title='Course project', created_by=self.student)
        with self.assertRaises(ValidationError):
            Project.objects.create(project_type=self.normal_type, course=self.course, title='Research', created_by=self.student)
        with self.assertRaises(ValidationError):
            ProjectRequest.objects.create(project_type=self.course_type, title='Course request', teacher=self.teacher)
        with self.assertRaises(ValidationError):
            ProjectRequest.objects.create(project_type=self.normal_type, course=self.course, title='Research request', teacher=self.teacher)

    def test_forms_filter_inactive_course_and_apply_invariant(self):
        self.course.is_active = False
        self.course.save()
        self.assertNotIn(self.course, RequestForm().fields['course'].queryset)
        self.assertNotIn(self.course, ProjectForm(current_user=self.student).fields['course'].queryset)
        request = ProjectRequest.objects.create(project_type=self.course_type, course=self.course, title='Old request', teacher=self.teacher)
        self.assertIn(self.course, RequestForm(instance=request).fields['course'].queryset)

    def test_bound_forms_reject_missing_and_injected_course(self):
        project_data = {'title': 'New project', 'creation_source': 'STUDENT_IDEA',
                        'development_status': 'idea', 'visibility': 'private'}
        form = ProjectForm(data={**project_data, 'project_type': self.course_type.pk}, current_user=self.student)
        self.assertFalse(form.is_valid())
        self.assertIn('course', form.errors)
        form = ProjectForm(data={**project_data, 'project_type': self.normal_type.pk, 'course': self.course.pk}, current_user=self.student)
        self.assertFalse(form.is_valid())
        self.assertIn('course', form.errors)
        request_data = {'title': 'New request', 'status': 'open', 'supervision_type': 'supervised'}
        form = RequestForm(data={**request_data, 'project_type': self.course_type.pk})
        self.assertFalse(form.is_valid())
        self.assertIn('course', form.errors)
        form = RequestForm(data={**request_data, 'project_type': self.normal_type.pk, 'course': self.course.pk})
        self.assertFalse(form.is_valid())
        self.assertIn('course', form.errors)

    def test_request_acceptance_transfers_course(self):
        request = ProjectRequest.objects.create(project_type=self.course_type, course=self.course, title='Announcement', teacher=self.teacher, status='open')
        application = ProjectRequestApplication.objects.create(project_request=request, student=self.student, motivation='Interested')
        project, created = accept_project_request_application(application_id=application.pk, reviewer=self.teacher)
        self.assertTrue(created)
        self.assertEqual(project.course_id, self.course.pk)

    def test_only_teacher_can_be_course_instructor(self):
        with self.assertRaises(ValidationError):
            CourseInstructor.objects.create(course=self.course, instructor=self.student)
        CourseInstructor.objects.create(course=self.course, instructor=self.teacher)

    def test_course_code_is_unique_when_present_and_delete_retires(self):
        coded = Course.objects.create(name='Algorithms', code=' cs101 ')
        self.assertEqual(coded.code, 'CS101')
        with self.assertRaises(ValidationError):
            Course.objects.create(name='Other algorithms', code='CS101')
        coded.delete()
        coded.refresh_from_db()
        self.assertFalse(coded.is_active)


class MilestoneWorkflowTests(TestCase):
    def setUp(self):
        self.student = user_with_role('milestone-owner')
        self.member = user_with_role('milestone-member')
        self.advisor = user_with_role('milestone-advisor', 'teacher')
        self.instructor = user_with_role('milestone-instructor', 'teacher')
        self.unrelated = user_with_role('milestone-unrelated', 'teacher')
        self.admin = user_with_role('milestone-admin', 'teacher', staff=True)
        self.course = Course.objects.create(name='Milestone Course')
        CourseInstructor.objects.create(course=self.course, instructor=self.instructor)
        self.type = ProjectType.objects.get(code='COURSE')
        self.project = Project.objects.create(project_type=self.type, course=self.course, title='Project', created_by=self.student, advisor=self.advisor,
                                              development_status='in_progress', approval_status='approved')
        self.project.team.add(self.member)
        self.milestone = save_milestone(project=self.project, actor=self.advisor, values={
            'title': 'Prototype', 'description': '', 'order': 1, 'due_at': timezone.now() - timedelta(days=1),
            'max_score': 100, 'is_required': True,
        })

    def test_permissions_and_capstone_boundary(self):
        self.assertFalse(can_manage_project_milestones(self.student, self.project))
        self.assertFalse(can_manage_project_milestones(self.unrelated, self.project))
        self.assertTrue(can_manage_project_milestones(self.advisor, self.project))
        self.assertTrue(can_manage_project_milestones(self.instructor, self.project))
        self.assertTrue(can_manage_project_milestones(self.admin, self.project))
        self.assertTrue(can_submit_project_milestone(self.member, self.milestone))
        with self.assertRaises(PermissionDenied):
            save_milestone(project=self.project, actor=self.student, values={
                'title': 'Bad', 'order': 2, 'max_score': 10, 'is_required': True})
        with self.assertRaises(ValidationError):
            ProjectMilestone.objects.create(project=self.project, title='Bad direct', order=2, max_score=10, created_by=self.student)
        with self.assertRaises(PermissionDenied):
            submit_milestone(milestone=self.milestone, actor=self.unrelated)
        capstone = ProjectType.objects.get(code='CAPSTONE')
        capstone_project = Project.objects.create(project_type=capstone, title='Capstone', created_by=self.student)
        with self.assertRaises(ValidationError):
            ProjectMilestone.objects.create(project=capstone_project, title='Invalid', order=1, max_score=10, created_by=self.advisor)
        self.client.force_login(self.advisor)
        response = self.client.get(reverse('projects:milestone_create', args=[capstone_project.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.post(reverse('projects:milestone_delete', args=[capstone_project.pk, self.milestone.pk]),
                                          {'confirm_delete': 'yes'}).status_code, 404)

    def test_milestone_form_labels_are_turkish(self):
        form = ProjectMilestoneForm()
        self.assertEqual({name: form.fields[name].label for name in (
            'title', 'description', 'order', 'due_at', 'max_score', 'is_required'
        )}, {'title': 'Başlık', 'description': 'Açıklama', 'order': 'Sıra',
             'due_at': 'Son Teslim Tarihi', 'max_score': 'Azami Puan', 'is_required': 'Zorunlu'})

    def test_empty_milestone_delete_requires_permission_and_audits(self):
        url = reverse('projects:milestone_delete', args=[self.project.pk, self.milestone.pk])
        self.client.force_login(self.unrelated)
        self.assertEqual(self.client.post(url, {'confirm_delete': 'yes'}).status_code, 404)
        self.advisor.profile.user_type = 'student'
        self.advisor.profile.class_level = '2'
        self.advisor.profile.save(update_fields=['user_type', 'class_level'])
        self.client.force_login(self.advisor)
        self.assertEqual(self.client.post(url, {'confirm_delete': 'yes'}).status_code, 404)
        self.advisor.profile.user_type = 'teacher'
        self.advisor.profile.class_level = None
        self.advisor.profile.save(update_fields=['user_type', 'class_level'])
        self.client.force_login(self.advisor)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url, {})
        self.assertTrue(ProjectMilestone.objects.filter(pk=self.milestone.pk).exists())
        response = self.client.post(url, {'confirm_delete': 'yes'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProjectMilestone.objects.filter(pk=self.milestone.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action='project.milestone.deleted',
                                                target_id=str(self.milestone.pk)).exists())

    def test_milestone_with_academic_history_cannot_be_deleted(self):
        submit_milestone(milestone=self.milestone, actor=self.member)
        self.client.force_login(self.advisor)
        response = self.client.post(reverse('projects:milestone_delete', args=[self.project.pk, self.milestone.pk]),
                                    {'confirm_delete': 'yes'}, follow=True)
        self.assertContains(response, 'Teslim veya değerlendirme geçmişi bulunan proje aşaması silinemez.')
        self.assertTrue(ProjectMilestone.objects.filter(pk=self.milestone.pk).exists())

    def test_revoked_or_downgraded_instructor_cannot_use_old_urls(self):
        submission = submit_milestone(milestone=self.milestone, actor=self.member)
        self.client.force_login(self.unrelated)
        self.assertEqual(self.client.get(reverse('projects:milestone_edit', args=[self.project.pk, self.milestone.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('projects:milestone_review', args=[submission.pk]), {
            'outcome': 'APPROVED', 'score': '50',
        }).status_code, 404)

        assignment = CourseInstructor.objects.get(course=self.course, instructor=self.instructor)
        assignment.is_active = False
        assignment.save()
        self.client.force_login(self.instructor)
        self.assertEqual(self.client.post(reverse('projects:milestone_review', args=[submission.pk]), {
            'outcome': 'APPROVED', 'score': '50',
        }).status_code, 404)
        assignment.is_active = True
        assignment.save()
        self.instructor.profile.user_type = 'student'
        self.instructor.profile.class_level = '2'
        self.instructor.profile.save()
        self.assertEqual(self.client.post(reverse('projects:milestone_review', args=[submission.pk]), {
            'outcome': 'APPROVED', 'score': '50',
        }).status_code, 404)
        self.assertFalse(ProjectMilestoneReview.objects.filter(submission=submission).exists())
        self.assertEqual(self.client.get(reverse('projects:project_detail', args=[self.project.pk])).status_code, 302)
        self.assertNotIn(self.project, self.client.get(reverse('projects:project_list')).context['projects'])
        assignment.is_active = False
        assignment.save(update_fields=['is_active'])

    def test_attempt_review_score_immutability_and_lateness(self):
        first = submit_milestone(milestone=self.milestone, actor=self.member, note='Draft')
        self.assertEqual(Notification.objects.filter(dedupe_key=f'milestone-submission-{first.pk}').count(), 2)
        self.assertEqual((first.attempt_number, first.is_late, self.milestone.state), (1, True, 'AWAITING_REVIEW'))
        with self.assertRaises(ValidationError):
            submit_milestone(milestone=self.milestone, actor=self.member)
        with self.assertRaises(ValidationError):
            review_milestone(submission=first, actor=self.advisor, outcome='APPROVED', score=101)
        review = review_milestone(submission=first, actor=self.instructor, outcome='REVISION_REQUIRED', feedback='Fix this')
        with self.assertRaises(ValidationError):
            review.save()
        with self.assertRaises(ValidationError):
            first.save()
        second = submit_milestone(milestone=self.milestone, actor=self.member, note='Updated')
        self.assertEqual(second.attempt_number, 2)
        with self.assertRaises(ValidationError):
            review_milestone(submission=first, actor=self.advisor, outcome='APPROVED', score=80)
        review_milestone(submission=second, actor=self.advisor, outcome='APPROVED', score=85)
        self.assertEqual(Notification.objects.filter(dedupe_key=f'milestone-review-{second.review.pk}').count(), 2)
        self.assertTrue(AuditLog.objects.filter(action='project.milestone.reviewed', target_id=str(second.review.pk)).exists())
        self.assertEqual(self.project.milestone_score['earned'], 85)
        with self.assertRaises(ValidationError):
            submit_milestone(milestone=self.milestone, actor=self.member)
        with self.assertRaises(ValidationError):
            review_milestone(submission=second, actor=self.advisor, outcome='APPROVED', score=85)

    def test_course_lock_and_completion(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse('projects:complete_project', args=[self.project.pk]))
        self.project.refresh_from_db()
        self.assertNotEqual(self.project.development_status, 'completed')
        self.client.force_login(self.advisor)
        self.client.post(reverse('projects:complete_project', args=[self.project.pk]))
        self.project.refresh_from_db()
        self.assertEqual(self.project.development_status, 'completed')
        self.assertTrue(AuditLog.objects.filter(action='project.completion_overridden', target_id=str(self.project.pk)).exists())
        submit_milestone(milestone=self.milestone, actor=self.member)
        self.project.course = Course.objects.create(name='Other')
        with self.assertRaises(ValidationError):
            self.project.save()

    def test_optional_milestone_does_not_block_completion(self):
        self.milestone.is_required = False
        self.milestone.save()
        self.client.force_login(self.student)
        self.client.post(reverse('projects:complete_project', args=[self.project.pk]))
        self.project.refresh_from_db()
        self.assertEqual(self.project.development_status, 'completed')

    def test_project_without_milestones_keeps_completion_behavior(self):
        other = Project.objects.create(project_type=ProjectType.objects.get(code='RESEARCH'), title='No milestones',
                                       created_by=self.student, development_status='in_progress', approval_status='approved')
        self.client.force_login(self.student)
        self.client.post(reverse('projects:complete_project', args=[other.pk]))
        other.refresh_from_db()
        self.assertEqual(other.development_status, 'completed')

    def test_unsafe_link_and_oversized_file_are_rejected(self):
        with self.assertRaises(ValidationError):
            submit_milestone(milestone=self.milestone, actor=self.member, links=['http://127.0.0.1/private'])
        upload = SimpleUploadedFile('large.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf')
        upload.size = 21 * 1024 * 1024
        with self.assertRaises(ValidationError):
            submit_milestone(milestone=self.milestone, actor=self.member, files=[upload])
        self.assertFalse(ProjectMilestoneSubmission.objects.filter(milestone=self.milestone).exists())

    def test_advisor_who_teaches_course_receives_one_notification(self):
        CourseInstructor.objects.create(course=self.course, instructor=self.advisor)
        submission = submit_milestone(milestone=self.milestone, actor=self.member)
        self.assertEqual(Notification.objects.filter(recipient=self.advisor,
            dedupe_key=f'milestone-submission-{submission.pk}').count(), 1)

    def test_private_file_download(self):
        pdf = SimpleUploadedFile('proof.pdf', b'%PDF-1.4\n%%EOF', content_type='application/pdf')
        with tempfile.TemporaryDirectory() as directory:
            field = ProjectMilestoneSubmission._meta.get_field('milestone')
            from .models import ProjectMilestoneSubmissionFile
            storage = ProjectMilestoneSubmissionFile._meta.get_field('file').storage
            original = storage.location
            storage.location = directory
            try:
                submission = submit_milestone(milestone=self.milestone, actor=self.member, files=[pdf])
                item = submission.files.get()
                self.client.force_login(self.unrelated)
                self.assertEqual(self.client.get(reverse('projects:milestone_file', args=[item.pk])).status_code, 404)
                self.client.force_login(self.student)
                response = self.client.get(reverse('projects:milestone_file', args=[item.pk]))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
                self.assertEqual(response['Cache-Control'], 'private, no-store')
                self.assertIn('attachment', response['Content-Disposition'])
                for viewer in (self.member, self.advisor, self.instructor, self.admin):
                    self.client.force_login(viewer)
                    self.assertEqual(self.client.get(reverse('projects:milestone_file', args=[item.pk])).status_code, 200)
                self.client.force_login(self.member)
                detail = self.client.get(reverse('projects:project_detail', args=[self.project.pk]))
                self.assertEqual(detail.status_code, 200)
                self.assertNotIn(item.file.name, detail.content.decode())
                with self.assertRaises(NotImplementedError):
                    item.file.url
            finally:
                storage.location = original

    def test_milestone_endpoints_create_submit_and_review(self):
        self.client.force_login(self.advisor)
        created = self.client.post(reverse('projects:milestone_create', args=[self.project.pk]), {
            'title': 'Final report', 'description': 'Document results', 'order': 2,
            'due_at': '', 'max_score': 50, 'is_required': 'on',
        })
        self.assertEqual(created.status_code, 302)
        milestone = ProjectMilestone.objects.get(project=self.project, order=2)
        self.client.force_login(self.member)
        submitted = self.client.post(reverse('projects:milestone_submit', args=[milestone.pk]), {
            'completion_note': 'Done', 'evidence_links': 'https://example.com/report',
        })
        self.assertEqual(submitted.status_code, 302)
        submission = milestone.submissions.get()
        self.assertEqual(submission.links.count(), 1)
        self.client.force_login(self.instructor)
        reviewed = self.client.post(reverse('projects:milestone_review', args=[submission.pk]), {
            'outcome': 'APPROVED', 'score': '45', 'feedback': 'Good',
        })
        self.assertEqual(reviewed.status_code, 302)
        self.assertEqual(submission.review.score, 45)
