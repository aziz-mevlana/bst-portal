from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from projects.models import Course, CourseInstructor, Project, ProjectType, ProjectMilestone
from projects.milestone_services import submit_milestone


class CourseProjectFilterTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('filter-teacher', password='password')
        self.teacher.profile.user_type = 'teacher'
        self.teacher.profile.save()
        self.student = User.objects.create_user('filter-student', password='password')
        self.student.profile.class_level = '2'
        self.student.profile.save()
        self.course = Course.objects.create(name='Algorithms')
        self.other = Course.objects.create(name='Databases')
        CourseInstructor.objects.create(course=self.course, instructor=self.teacher)
        kind = ProjectType.objects.get(code='COURSE')
        self.first = Project.objects.create(project_type=kind, course=self.course, title='Algorithms Project',
                                            created_by=self.student, visibility='public', approval_status='approved')
        self.second = Project.objects.create(project_type=kind, course=self.other, title='Database Project',
                                             created_by=self.student, visibility='public', approval_status='approved')

    def test_public_course_filter_combines_with_type_and_load_more(self):
        params = {'course': self.course.slug, 'type': str(self.first.project_type_id), 'view': 'list'}
        response = self.client.get(reverse('projects:project_list'), params)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.first.title)
        self.assertNotContains(response, self.second.title)
        self.assertContains(response, 'Ders: Algorithms')
        self.assertContains(response, 'id="project-grid" class="space-y-3"')
        self.assertContains(response, 'name="view" value="list"')
        more = self.client.get(reverse('projects:project_load_more'), params)
        self.assertIn(self.first.title, more.json()['items'])
        self.assertNotIn(self.second.title, more.json()['items'])

    def test_teacher_scope_only_related_course_and_advised_projects(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('dashboard:projects'), {'scope': 'course', 'course': self.course.slug, 'view': 'list'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.first.title)
        self.assertNotContains(response, self.second.title)
        self.assertContains(response, 'id="dashboard-project-grid" class="space-y-3"')
        more = self.client.get(reverse('dashboard:projects_load_more'), {'scope': 'course', 'course': self.course.slug, 'view': 'list'})
        self.assertIn(self.first.title, more.json()['items'])
        self.assertNotIn(self.second.title, more.json()['items'])

    def test_pending_review_scope_and_teacher_home(self):
        milestone = ProjectMilestone.objects.create(project=self.first, title='Report', order=1, max_score=100, created_by=self.teacher)
        submit_milestone(milestone=milestone, actor=self.student)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('dashboard:projects'), {'scope': 'pending-review'})
        self.assertContains(response, self.first.title)
        self.assertNotContains(response, self.second.title)
        home = self.client.get(reverse('dashboard:home'))
        self.assertContains(home, 'Değerlendirme Bekleyenler')
        self.assertContains(home, 'Derslerim')
        self.assertContains(home, 'Danışmanlıklarım')

    def test_teacher_cannot_create_course(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse('dashboard:course_create'), {'name': 'Forbidden'})
        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_and_assign_teacher(self):
        admin = User.objects.create_user('course-admin', is_staff=True)
        self.client.force_login(admin)
        response = self.client.post(reverse('dashboard:course_create'), {'name': 'Networks', 'code': 'CS101', 'slug': '', 'is_active': 'on'})
        self.assertEqual(response.status_code, 302)
        course = Course.objects.get(name='Networks')
        response = self.client.post(reverse('dashboard:course_instructor_change', args=[course.pk]), {'instructor_id': self.teacher.pk, 'action': 'assign'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(CourseInstructor.objects.filter(course=course, instructor=self.teacher, is_active=True).exists())
