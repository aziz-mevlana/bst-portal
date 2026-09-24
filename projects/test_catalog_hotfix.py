from importlib import import_module

from django.apps import apps
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from .forms import ProjectForm, RequestForm
from .models import Course, CourseCatalogEntry, CourseInstructor, Project, ProjectRequest, ProjectType


catalog_migration = import_module('projects.migrations.0027_course_catalog_2026_2027')


class CourseCatalogHotfixTests(TestCase):
    def test_whitelist_and_semesters(self):
        entries = CourseCatalogEntry.objects.filter(academic_year='2026-2027')
        self.assertEqual(entries.count(), 27)
        self.assertEqual(entries.filter(semester='FALL').count(), 14)
        self.assertEqual(entries.filter(semester='SPRING').count(), 13)
        self.assertEqual(entries.values('course_id').distinct().count(), 27)
        self.assertEqual(entries.filter(course__code='BST 401').count(), 1)
        self.assertEqual(entries.get(course__code='BST 103').display_name,
                         'Algoritma Bilgisayar Programlamaya Giriş')
        self.assertEqual(set(entries.values_list('course__code', flat=True)),
                         {row[0] for row in catalog_migration.FALL + catalog_migration.SPRING})
        self.assertFalse(entries.filter(course__name__icontains='Seçmeli').exists())

    def test_repeat_seed_preserves_history_and_does_not_duplicate(self):
        historical = Course.objects.create(code='OLD 101', name='Eski dönem dersi')
        legacy_same_code = Course.objects.get(code='BST 103')
        legacy_same_code.name = 'Tarihsel ders adı'
        legacy_same_code.save(update_fields=['name'])
        teacher = User.objects.create_user('catalog-harun', first_name='Harun', last_name='ÖZKİŞİ')
        teacher.profile.user_type = 'teacher'
        teacher.profile.save(update_fields=['user_type'])
        for username, first_name, last_name in (
            ('catalog-murat', 'Murat', 'TOPALOĞLU'),
            ('catalog-onur', 'Onur', 'KARA'),
            ('catalog-egemen', 'Egemen', 'TEKKANAT'),
        ):
            colleague = User.objects.create_user(username, first_name=first_name, last_name=last_name)
            colleague.profile.user_type = 'teacher'
            colleague.profile.save(update_fields=['user_type'])
        catalog_migration.seed_2026_2027(apps, type('Editor', (), {'connection': connection})())
        catalog_migration.seed_2026_2027(apps, type('Editor', (), {'connection': connection})())
        self.assertTrue(Course.objects.filter(pk=historical.pk).exists())
        legacy_same_code.refresh_from_db()
        self.assertEqual(legacy_same_code.name, 'Tarihsel ders adı')
        self.assertEqual(CourseCatalogEntry.objects.get(course=legacy_same_code).display_name,
                         'Algoritma Bilgisayar Programlamaya Giriş')
        self.assertEqual(CourseCatalogEntry.objects.filter(academic_year='2026-2027').count(), 27)
        self.assertEqual(Course.objects.filter(code='BST 401').count(), 1)
        self.assertEqual(CourseInstructor.objects.filter(
            course__code='BST 103', instructor=teacher, is_active=True).count(), 1)
        self.assertEqual(CourseInstructor.objects.filter(course__code='BST 401', is_active=True).count(), 4)
        self.assertFalse(CourseInstructor.objects.filter(
            course__catalog_entries__academic_year='2026-2027',
            course__catalog_entries__semester='SPRING').exists())
        self.assertFalse(User.objects.filter(first_name='Gürkan', last_name='KOLAYLI').exists())

    def test_bitirme_courses_are_not_generic_course_choices(self):
        student = User.objects.create_user('catalog-student')
        student.profile.class_level = '4'
        student.profile.save(update_fields=['class_level'])
        for form in (ProjectForm(current_user=student), RequestForm()):
            self.assertFalse(form.fields['course'].queryset.filter(code__in=('BST 401', 'BST 402')).exists())
        self.client.force_login(student)
        course_type = ProjectType.objects.get(code='COURSE')
        response = self.client.get(reverse('projects:project_create'))
        self.assertFalse(response.context['form'].fields['project_type'].queryset.filter(code='CAPSTONE').exists())
        self.assertFalse(response.context['form'].fields['course'].queryset.filter(code='BST 401').exists())
        self.assertEqual(course_type.code, 'COURSE')

    def test_direct_generic_creation_cannot_use_bitirme_courses(self):
        student = User.objects.create_user('direct-course-student')
        course_type = ProjectType.objects.get(code='COURSE')
        for code in ('BST 401', 'BST 402'):
            course = Course.objects.get(code=code)
            with self.subTest(code=code), self.assertRaises(ValidationError):
                Project.objects.create(project_type=course_type, course=course,
                                       created_by=student, title=f'{code} kaçak proje')
            with self.subTest(code=f'{code} request'), self.assertRaises(ValidationError):
                ProjectRequest.objects.create(project_type=course_type, course=course,
                                              title=f'{code} kaçak ilan')

    def test_ambiguous_teacher_name_is_not_assigned(self):
        for username in ('harun-one', 'harun-two'):
            teacher = User.objects.create_user(username, first_name='Harun', last_name='ÖZKİŞİ')
            teacher.profile.user_type = 'teacher'
            teacher.profile.save(update_fields=['user_type'])
        catalog_migration.seed_2026_2027(apps, type('Editor', (), {'connection': connection})())
        self.assertFalse(CourseInstructor.objects.filter(course__code='BST 103').exists())

    def test_catalog_screen_shows_term_and_class(self):
        admin = User.objects.create_user('catalog-admin', is_staff=True)
        self.client.force_login(admin)
        response = self.client.get(reverse('dashboard:courses'))
        self.assertContains(response, '2026–2027')
        self.assertContains(response, '1. sınıf')
        self.assertContains(response, 'Güz')
        self.assertContains(response, 'Bahar')
        self.assertContains(response, 'BST 401')
        self.assertContains(response, reverse('capstone:advisor_home'))
        self.assertNotContains(response, 'Eski dönem dersi')
