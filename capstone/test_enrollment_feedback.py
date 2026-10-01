from datetime import timedelta
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from core.models import AuditLog
from .models import CapstoneTerm, CapstoneEnrollment
from .academic_services import enroll_student, remove_enrollment, claim_student, initialize_project
from .policies import is_capstone_eligible_student


class EnrollmentFeedbackTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_user('enroll-admin',is_staff=True)
        self.student=User.objects.create_user('enroll-student',first_name='Tekrar',last_name='Aday')
        self.student.profile.class_level='4';self.student.profile.save()
        self.teacher=User.objects.create_user('enroll-teacher')
        self.teacher.profile.user_type='teacher';self.teacher.profile.save()
        self.now=timezone.now()
        self.term=CapstoneTerm.objects.create(academic_year='2026-2027',semester='FALL',is_active=True,
            starts_at=self.now-timedelta(days=1),midterm_at=self.now+timedelta(days=50),final_at=self.now+timedelta(days=100))

    def test_remove_and_readd_candidate_preserves_old_audit(self):
        enrollment=enroll_student(term=self.term,student=self.student,actor=self.admin)
        old_pk=enrollment.pk
        remove_enrollment(enrollment=enrollment,actor=self.admin,reason='Yanlış kayıt')
        self.client.force_login(self.admin)
        page=self.client.get(reverse('capstone:student_pool'))
        self.assertContains(page,'Tekrar Aday');self.assertIn(self.student,list(page.context['eligible']))
        response=self.client.post(reverse('capstone:student_enroll'),{'student_id':self.student.pk})
        self.assertEqual(response.status_code,302)
        self.assertNotEqual(CapstoneEnrollment.objects.get(student=self.student,term=self.term).pk,old_pk)
        self.assertTrue(AuditLog.objects.filter(action='capstone.enrollment_removed',metadata__enrollment_id=old_pk).exists())

    def test_inactive_enrollment_in_other_term_does_not_hide_candidate(self):
        enrollment=enroll_student(term=self.term,student=self.student,actor=self.admin)
        enrollment.is_active=False;enrollment.save()
        self.client.force_login(self.admin)
        page=self.client.get(reverse('capstone:student_pool'))
        self.assertIn(self.student,list(page.context['eligible']))
        current=enroll_student(term=self.term,student=self.student,actor=self.admin)
        self.assertEqual(current.pk,enrollment.pk);self.assertTrue(current.is_active)
        self.assertTrue(AuditLog.objects.filter(action='capstone.enrollment_reactivated').exists())

    def test_admin_exception_requires_reason_confirmation_and_supports_full_workflow(self):
        self.student.profile.class_level='3';self.student.profile.save()
        for values in ({},{'override':True},{'override':True,'reason':'İstisna'},{'override':True,'reason':' ','confirmed':True}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                enroll_student(term=self.term,student=self.student,actor=self.admin,**values)
        enrollment=enroll_student(term=self.term,student=self.student,actor=self.admin,override=True,reason='Alttan ders',confirmed=True)
        self.assertTrue(enrollment.eligibility_override);self.assertEqual(enrollment.eligibility_override_reason,'Alttan ders')
        self.assertTrue(is_capstone_eligible_student(self.student,self.term));self.student.profile.refresh_from_db();self.assertEqual(self.student.profile.class_level,'3')
        claim_student(enrollment=enrollment,advisor=self.teacher)
        project=initialize_project(enrollment=enrollment,student=self.student,title='İstisna Projesi',description='Çözüm fikri')
        self.assertEqual(project.project.created_by_id,self.student.pk)
        self.assertTrue(AuditLog.objects.filter(action='capstone.enrollment_created',metadata__eligibility_override=True,metadata__reason='Alttan ders').exists())

    def test_admin_search_class_warning_and_teacher_cannot_override(self):
        self.student.profile.class_level='3';self.student.profile.save()
        self.client.force_login(self.admin)
        self.assertNotIn(self.student,list(self.client.get(reverse('capstone:student_pool')).context['eligible']))
        page=self.client.get(reverse('capstone:student_pool'),{'q':'Tekrar'})
        self.assertContains(page,'3. sınıf');self.assertContains(page,'İstisna Olarak Resmi Listeye Ekle')
        for actor in (self.teacher,self.student):
            self.client.force_login(actor)
            self.assertEqual(self.client.post(reverse('capstone:student_enroll'),{'student_id':self.student.pk,'override':'yes','confirm':'yes','reason':'Sahte'}).status_code,404)
        with self.assertRaises(PermissionDenied):
            enroll_student(term=self.term,student=self.student,actor=self.teacher,override=True,reason='Sahte',confirmed=True)

    def test_malformed_student_identifiers_are_404(self):
        self.client.force_login(self.admin)
        for student_id in ('garbage','-1','999999999999999999999999999999999'):
            self.assertEqual(self.client.post(reverse('capstone:student_enroll'),{'student_id':student_id}).status_code,404)
