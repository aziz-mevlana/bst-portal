from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from projects.models import Project, ProjectType
from .academic_services import remove_enrollment, initialize_project
from .models import CapstoneEnrollment, CapstoneTerm


class EnrollmentHotfixTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.term = CapstoneTerm.objects.create(academic_year='2026-2027', semester='FALL',
            starts_at=now-timedelta(days=1), midterm_at=now+timedelta(days=30),
            final_at=now+timedelta(days=90), is_active=True)
        self.admin = User.objects.create_user('enrollment-admin', is_staff=True)
        self.teacher = User.objects.create_user('enrollment-teacher')
        self.teacher.profile.user_type = 'teacher'
        self.teacher.profile.save()
        self.student = User.objects.create_user('enrollment-student')
        self.student.profile.class_level = '4'
        self.student.profile.save()
        self.enrollment = CapstoneEnrollment.objects.create(term=self.term, student=self.student, advisor=self.teacher)

    def test_admin_remove_only_target_and_preserve_unrelated(self):
        other_term = CapstoneTerm.objects.create(academic_year='2025-2026', semester='FALL',
            starts_at=self.term.starts_at-timedelta(days=365), midterm_at=self.term.midterm_at-timedelta(days=365),
            final_at=self.term.final_at-timedelta(days=365))
        other_period = CapstoneEnrollment.objects.create(term=other_term, student=self.student)
        other_student = User.objects.create_user('other-enrollment-student')
        other_student.profile.class_level = '4'
        other_student.profile.save()
        other_enrollment = CapstoneEnrollment.objects.create(term=self.term, student=other_student)
        unrelated = Project.objects.create(project_type=ProjectType.objects.get(code='RESEARCH'),
                                           title='Başka proje', created_by=self.student)
        enrollment_id = self.enrollment.pk
        remove_enrollment(enrollment=self.enrollment, actor=self.admin, reason='Yanlış test kaydı')
        self.assertFalse(CapstoneEnrollment.objects.filter(pk=enrollment_id).exists())
        self.assertTrue(CapstoneEnrollment.objects.filter(pk=other_period.pk).exists())
        self.assertTrue(CapstoneEnrollment.objects.filter(pk=other_enrollment.pk).exists())
        self.assertTrue(Project.objects.filter(pk=unrelated.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.student.pk).exists())
        self.assertTrue(self.student.profile.__class__.objects.filter(user=self.student).exists())
        audit = AuditLog.objects.get(action='capstone.enrollment_removed')
        self.assertEqual(audit.metadata['term_id'], self.term.pk)
        self.assertEqual(audit.metadata['advisor_id'], self.teacher.pk)
        self.assertEqual(audit.metadata['reason'], 'Yanlış test kaydı')
        self.client.force_login(self.admin)
        response = self.client.get(reverse('capstone:student_pool'))
        self.assertNotIn(self.student.pk, [item.student_id for item in response.context['mine']])
        self.assertNotIn(self.student.pk, [item.student_id for item in response.context['pool']])

    def test_teacher_student_and_forged_id_denied(self):
        for actor in (self.teacher, self.student):
            with self.assertRaises(PermissionDenied):
                remove_enrollment(enrollment=self.enrollment, actor=actor, reason='Sahte')
            self.client.force_login(actor)
            for method in (self.client.get, self.client.post):
                self.assertEqual(method(reverse('capstone:enrollment_remove', args=[self.enrollment.pk])).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('capstone:enrollment_remove', args=[999999]),
            {'confirm': 'yes', 'reason': 'Sahte'}).status_code, 404)

    def test_reason_confirmation_and_post_remove(self):
        with self.assertRaises(ValidationError):
            remove_enrollment(enrollment=self.enrollment, actor=self.admin, reason=' ')
        self.client.force_login(self.admin)
        url = reverse('capstone:enrollment_remove', args=[self.enrollment.pk])
        self.assertContains(self.client.get(url), 'Resmi Listeden Çıkar')
        for values in ({'reason': 'Test'}, {'confirm': 'yes', 'reason': ''}):
            self.assertEqual(self.client.post(url, values).status_code, 200)
            self.assertTrue(CapstoneEnrollment.objects.filter(pk=self.enrollment.pk).exists())
        self.assertEqual(self.client.post(url, {'confirm': 'yes', 'reason': 'Test'}).status_code, 302)
        self.assertFalse(CapstoneEnrollment.objects.filter(pk=self.enrollment.pk).exists())

    def test_active_project_blocks_and_cta(self):
        project = initialize_project(enrollment=self.enrollment, student=self.student, title='Aktif', description='Proje')
        with self.assertRaises(ValidationError):
            remove_enrollment(enrollment=self.enrollment, actor=self.admin, reason='Test')
        self.client.force_login(self.admin)
        url = reverse('capstone:enrollment_remove', args=[self.enrollment.pk])
        self.assertContains(self.client.get(url), reverse('capstone:advisor_project_purge', args=[project.pk]))
        self.client.post(url, {'confirm': 'yes', 'reason': 'Test'})
        self.assertTrue(CapstoneEnrollment.objects.filter(pk=self.enrollment.pk).exists())
        self.assertTrue(Project.objects.filter(pk=project.project_id).exists())

    def test_class_mismatch_warning_and_no_automatic_delete(self):
        self.student.profile.class_level = '3'
        self.student.profile.save()
        for advisor in (self.teacher, None):
            self.enrollment.advisor = advisor
            CapstoneEnrollment.objects.filter(pk=self.enrollment.pk).update(advisor=advisor)
            for actor in (self.admin, self.teacher):
                self.client.force_login(actor)
                response = self.client.get(reverse('capstone:student_pool'))
                self.assertContains(response, 'Mevcut sınıf bilgisi: 3. sınıf — Bitirme Projesi resmi listesiyle uyuşmuyor.')
                if actor == self.teacher:
                    self.assertNotContains(response, 'Resmi Listeden Çıkar')
        self.assertTrue(CapstoneEnrollment.objects.filter(pk=self.enrollment.pk, is_active=True).exists())

    def test_remove_get_csrf_and_repeat_post_do_not_duplicate_history(self):
        from django.test import Client
        from core.models import Notification
        self.client.force_login(self.admin)
        url = reverse('capstone:enrollment_remove', args=[self.enrollment.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(CapstoneEnrollment.objects.filter(pk=self.enrollment.pk).exists())
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(url, {'confirm': 'yes', 'reason': 'Sahte'}).status_code, 403)
        self.assertEqual(self.client.post(url, {'confirm': 'yes', 'reason': 'Çıkar'}).status_code, 302)
        self.assertEqual(self.client.post(url, {'confirm': 'yes', 'reason': 'Çıkar'}).status_code, 404)
        self.assertEqual(AuditLog.objects.filter(action='capstone.enrollment_removed').count(), 1)
        self.assertEqual(Notification.objects.filter(dedupe_key__startswith='capstone-enrollment-removed-').count(), 1)

    def test_other_term_enrollment_id_is_not_removable_from_current_roster(self):
        other_term = CapstoneTerm.objects.create(academic_year='2025-2026', semester='FALL',
            starts_at=self.term.starts_at-timedelta(days=365), midterm_at=self.term.midterm_at-timedelta(days=365),
            final_at=self.term.final_at-timedelta(days=365))
        enrollment = CapstoneEnrollment.objects.create(term=other_term, student=self.student)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('capstone:enrollment_remove', args=[enrollment.pk]),
            {'confirm': 'yes', 'reason': 'Yanlış dönem'}).status_code, 404)
        self.assertTrue(CapstoneEnrollment.objects.filter(pk=enrollment.pk).exists())
