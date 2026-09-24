from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .academic_services import claim_student, initialize_project
from .models import CapstoneEnrollment, CapstoneTerm


class TeacherShellHotfixTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.term = CapstoneTerm.objects.create(
            academic_year='2026-2027', semester='FALL',
            starts_at=now - timedelta(days=1),
            midterm_at=now + timedelta(days=30),
            final_at=now + timedelta(days=90),
            is_active=True,
        )
        self.student = User.objects.create_user('shell-student')
        self.student.profile.class_level = '4'
        self.student.profile.save(update_fields=['class_level'])
        self.teacher = User.objects.create_user('shell-teacher')
        self.teacher.profile.user_type = 'teacher'
        self.teacher.profile.save(update_fields=['user_type'])
        enrollment = CapstoneEnrollment.objects.create(term=self.term, student=self.student)
        claim_student(enrollment=enrollment, advisor=self.teacher)
        self.project = initialize_project(
            enrollment=enrollment, student=self.student, title='Kabuk testi', description='Amaç')

    def test_teacher_pages_keep_dashboard_sidebar_and_dark_shell(self):
        self.client.force_login(self.teacher)
        urls = (
            reverse('capstone:advisor_home'),
            reverse('capstone:student_pool'),
            reverse('capstone:plan_home'),
            reverse('capstone:progress_matrix'),
            reverse('capstone:advisor_project_detail', args=[self.project.pk]),
            reverse('capstone:process_report', args=[self.project.pk]),
        )
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'id="dashboard-sidebar"')
                self.assertContains(response, 'capstone-teacher')
                self.assertContains(response, 'Akademisyen Paneli')
                self.assertNotContains(response, 'min-h-screen bg-slate-50 py-8')

    def test_student_workspace_stays_outside_teacher_shell(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('capstone:student_home'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="dashboard-sidebar"')
