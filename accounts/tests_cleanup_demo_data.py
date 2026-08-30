from datetime import date, timedelta
from importlib import import_module
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.management.commands.cleanup_demo_data import Command
from accounts.models import (
    ConsentRecord,
    DataSubjectRequest,
    EmailVerification,
    UserModerationAction,
    UserReport,
    WebsiteModerationHistory,
)
from ai_assistant.models import ChatCache, KnowledgeSource
from alumni.models import Alumni, AlumniRegistrationRequest, WorkExperience
from career.models import CollaborationRequest, Opportunity
from core.models import AuditLog, FooterLink, Notification
from events.models import Event, EventRegistration
from news.models import Article
from projects.models import (
    Project,
    ProjectCategory,
    ProjectComment,
    ProjectLike,
    ProjectRequest,
    ProjectRequestApplication,
    ProjectSave,
    ProjectType,
    Team,
    TeamInvitation,
    Technology,
)


class CleanupDemoDataCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project_type = ProjectType.objects.create(
            code='CLEANUP_TEST', name='Cleanup Test Type', slug='cleanup-test-type'
        )
        cls.category = ProjectCategory.objects.create(name='Kalıcı Kategori')
        cls.technology = Technology.objects.create(name='Kalıcı Teknoloji')
        cls.footer = FooterLink.objects.create(
            section='legal', label='Kalıcı Ayar', url='/kalici-ayar/'
        )

        cls.admin = User.objects.create_superuser(
            'demo-admin', 'admin@example.com', 'Strong-Test-123!'
        )
        cls.teacher = cls._user('demo-teacher', 'teacher@example.com', 'teacher')
        cls.authority = cls._user('demo-authority', 'authority@example.com', 'staff_student')
        cls.real_student = cls._user('real-student', 'student@bst.edu.tr', 'student')
        cls.real_visitor = cls._user('real-visitor', 'visitor@company.org', 'visitor')

        cls.alumni_user = cls._user('demo-alumni', 'alumni@example.com', 'alumni')
        cls.alumni = Alumni.objects.create(
            user=cls.alumni_user,
            full_name='Gerçek Mezun',
            graduation_year=2020,
            student_number='ALUMNI-CLEANUP-1',
        )
        cls.work_experience = WorkExperience.objects.create(
            person=cls.alumni,
            company='Kalıcı Şirket',
            position='Mühendis',
            start_date=date(2021, 1, 1),
            is_current=True,
            description='Gerçek iş geçmişi',
        )

        cls.demo_student = cls._user('demo-student', 'student@example.com', 'student')
        cls.demo_visitor = cls._user('test-visitor', 'visitor@example.test', 'visitor')
        cls.demo_member = cls._user('demo-member', 'member@test.local', 'approved_member')

        cls.real_project = Project.objects.create(
            title='Gerçek Proje',
            project_type=cls.project_type,
            created_by=cls.real_student,
            visibility='public',
        )
        cls.real_project.categories.add(cls.category)
        cls.real_project.technologies.add(cls.technology)
        cls.demo_project = Project.objects.create(
            title='Demo öğrencinin projesi',
            project_type=cls.project_type,
            created_by=cls.demo_student,
        )
        cls.demo_project.categories.add(cls.category)
        ProjectComment.objects.create(
            project=cls.real_project, author=cls.demo_student, content='Test yorum'
        )
        ProjectLike.objects.create(project=cls.real_project, user=cls.demo_student)
        ProjectSave.objects.create(project=cls.real_project, user=cls.demo_student)

        cls.real_request = ProjectRequest.objects.create(
            title='Gerçek Akademisyen İlanı', project_type=cls.project_type, teacher=cls.teacher
        )
        cls.demo_request = ProjectRequest.objects.create(
            title='Demo İlan', project_type=cls.project_type, teacher=cls.demo_student
        )
        ProjectRequestApplication.objects.create(
            project_request=cls.real_request,
            student=cls.demo_student,
            motivation='Test başvuru',
        )

        cls.demo_team = Team.objects.create(name='Demo Ekip', leader=cls.demo_student)
        TeamInvitation.objects.create(
            team=cls.demo_team,
            invited_user=cls.real_student,
            invited_by=cls.demo_student,
        )

        now = timezone.now()
        cls.real_event = Event.objects.create(
            title='Gerçek Etkinlik',
            description='Kalıcı',
            event_type='seminar',
            location='Kampüs',
            start_date=now + timedelta(days=2),
            end_date=now + timedelta(days=2, hours=1),
            created_by=cls.admin,
        )
        cls.demo_event = Event.objects.create(
            title='Demo kullanıcının etkinliği',
            description='Test',
            event_type='workshop',
            location='Test',
            start_date=now + timedelta(days=3),
            end_date=now + timedelta(days=3, hours=1),
            created_by=cls.demo_student,
        )
        cls.marked_event = Event.objects.create(
            title='[DEMO] Yönetici etkinliği',
            description='Açıkça işaretli demo',
            event_type='other',
            location='Test',
            start_date=now + timedelta(days=4),
            end_date=now + timedelta(days=4, hours=1),
            created_by=cls.admin,
        )
        EventRegistration.objects.create(event=cls.real_event, user=cls.demo_student)

        cls.demo_article = Article.objects.create(
            title='Demo haber',
            summary='Test',
            content='Test',
            created_by=cls.demo_student,
        )
        cls.real_article = Article.objects.create(
            title='Gerçek haber', summary='Kalıcı', content='Kalıcı', created_by=cls.admin
        )
        cls.fetched_demo_article = Article.objects.create(
            title='Üretici demo haberi',
            summary='Test',
            content='Test',
            source='TechDemo',
            source_url='https://example.com/demo-news',
        )

        cls.demo_opportunity = Opportunity.objects.create(
            title='Demo ilan',
            opportunity_type='internship',
            organization='Demo Kurum',
            description='Test',
            work_mode='remote',
            application_url='https://example.com/apply',
            contact_method='url',
            created_by=cls.demo_member,
        )
        cls.demo_collaboration = CollaborationRequest.objects.create(
            contact_name='Test Kişi',
            organization='Test Kurum',
            job_title='Test',
            email='contact@example.com',
            request_type='project',
            title='Demo iş birliği',
            description='Test',
        )
        cls.knowledge = KnowledgeSource.objects.create(
            title='Demo kaynak', content='Test', created_by=cls.demo_student
        )
        cls.chat_cache = ChatCache.objects.create(
            question='test',
            question_hash=ChatCache.get_hash('test'),
            response='test',
        )

        Notification.objects.create(
            recipient=cls.real_student,
            actor=cls.demo_student,
            notification_type='project_comment',
            message='Demo bildirim',
        )
        Notification.objects.create(
            recipient=cls.demo_student,
            notification_type='system',
            message='Demo kullanıcı bildirimi',
        )
        ConsentRecord.objects.create(
            user=cls.demo_student,
            consent_type='terms',
            text_version='test-v1',
            accepted=True,
        )
        DataSubjectRequest.objects.create(
            user=cls.demo_student, request_type='export', explanation='Test'
        )
        UserModerationAction.objects.create(
            user=cls.demo_student,
            action_type='suspend',
            reason='spam',
            description='Test moderasyon',
            performed_by=cls.admin,
        )
        WebsiteModerationHistory.objects.bulk_create(
            [
                WebsiteModerationHistory(
                    profile=cls.demo_student.profile,
                    website_url='https://example.com',
                    status='rejected',
                    reason='spam',
                    description='Test onay',
                    performed_by=cls.admin,
                )
            ]
        )
        UserReport.objects.create(
            reporter=cls.real_student,
            reported_user=cls.demo_student,
            reason='spam',
            description='Test rapor',
        )
        AlumniRegistrationRequest.objects.create(
            user=cls.demo_visitor,
            full_name='Test Ziyaretçi',
            graduation_year=2024,
            email=cls.demo_visitor.email,
            reviewed_by=cls.admin,
        )
        EmailVerification.objects.create(email=cls.demo_student.email)
        cls.audit_log = AuditLog.objects.create(
            actor=cls.demo_student,
            action='demo.action',
            target_type='auth.user',
            target_id=str(cls.demo_student.pk),
        )

        session_engine = import_module(settings.SESSION_ENGINE)
        session = session_engine.SessionStore()
        session['_auth_user_id'] = str(cls.demo_student.pk)
        session['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
        session.save()
        cls.demo_session_key = session.session_key

    @staticmethod
    def _user(username, email, role):
        user = User.objects.create_user(username, email, 'Strong-Test-123!')
        user.profile.user_type = role
        user.profile.save(update_fields=['user_type', 'class_level'])
        return user

    def test_default_mode_is_dry_run_and_changes_nothing(self):
        output = StringIO()
        before = {
            'users': User.objects.count(),
            'projects': Project.objects.count(),
            'events': Event.objects.count(),
            'articles': Article.objects.count(),
            'consents': ConsentRecord.objects.count(),
        }

        call_command('cleanup_demo_data', stdout=output, no_color=True)

        self.assertEqual(before['users'], User.objects.count())
        self.assertEqual(before['projects'], Project.objects.count())
        self.assertEqual(before['events'], Event.objects.count())
        self.assertEqual(before['articles'], Article.objects.count())
        self.assertEqual(before['consents'], ConsentRecord.objects.count())
        self.assertIn('DRY-RUN', output.getvalue())
        self.assertIn('transaction geri alındı, veri değişmedi', output.getvalue())
        self.assertIn("username='demo-student'", output.getvalue())
        self.assertIn("username='demo-admin': superuser", output.getvalue())

    def test_confirm_deletes_demo_scope_and_preserves_protected_data(self):
        output = StringIO()

        call_command('cleanup_demo_data', confirm=True, stdout=output, no_color=True)

        for user in (self.demo_student, self.demo_visitor, self.demo_member):
            self.assertFalse(User.objects.filter(pk=user.pk).exists())
        for user in (
            self.admin,
            self.teacher,
            self.authority,
            self.alumni_user,
            self.real_student,
            self.real_visitor,
        ):
            self.assertTrue(User.objects.filter(pk=user.pk).exists())

        self.assertFalse(Project.objects.filter(pk=self.demo_project.pk).exists())
        self.assertTrue(Project.objects.filter(pk=self.real_project.pk).exists())
        self.assertFalse(ProjectComment.objects.filter(author_id=self.demo_student.pk).exists())
        self.assertFalse(ProjectLike.objects.filter(user_id=self.demo_student.pk).exists())
        self.assertFalse(ProjectSave.objects.filter(user_id=self.demo_student.pk).exists())
        self.assertFalse(ProjectRequest.objects.filter(pk=self.demo_request.pk).exists())
        self.assertTrue(ProjectRequest.objects.filter(pk=self.real_request.pk).exists())
        self.assertFalse(
            ProjectRequestApplication.objects.filter(student_id=self.demo_student.pk).exists()
        )
        self.assertFalse(Team.objects.filter(pk=self.demo_team.pk).exists())
        self.assertFalse(Event.objects.filter(pk=self.demo_event.pk).exists())
        self.assertFalse(Event.objects.filter(pk=self.marked_event.pk).exists())
        self.assertTrue(Event.objects.filter(pk=self.real_event.pk).exists())
        self.assertFalse(EventRegistration.objects.filter(user_id=self.demo_student.pk).exists())
        self.assertFalse(Article.objects.filter(pk=self.demo_article.pk).exists())
        self.assertFalse(Article.objects.filter(pk=self.fetched_demo_article.pk).exists())
        self.assertTrue(Article.objects.filter(pk=self.real_article.pk).exists())
        self.assertFalse(Opportunity.objects.filter(pk=self.demo_opportunity.pk).exists())
        self.assertFalse(CollaborationRequest.objects.filter(pk=self.demo_collaboration.pk).exists())
        self.assertFalse(KnowledgeSource.objects.filter(pk=self.knowledge.pk).exists())
        self.assertFalse(ChatCache.objects.filter(pk=self.chat_cache.pk).exists())
        self.assertFalse(Notification.objects.filter(actor_id=self.demo_student.pk).exists())
        self.assertFalse(ConsentRecord.objects.filter(user_id=self.demo_student.pk).exists())
        self.assertFalse(DataSubjectRequest.objects.filter(user_id=self.demo_student.pk).exists())
        self.assertFalse(UserModerationAction.objects.filter(user_id=self.demo_student.pk).exists())
        self.assertFalse(
            WebsiteModerationHistory.objects.filter(profile_id=self.demo_student.profile.pk).exists()
        )
        self.assertFalse(UserReport.objects.filter(reported_user_id=self.demo_student.pk).exists())
        self.assertFalse(
            AlumniRegistrationRequest.objects.filter(user_id=self.demo_visitor.pk).exists()
        )
        self.assertFalse(EmailVerification.objects.filter(email=self.demo_student.email).exists())

        self.assertTrue(Alumni.objects.filter(pk=self.alumni.pk).exists())
        self.assertTrue(WorkExperience.objects.filter(pk=self.work_experience.pk).exists())
        self.assertTrue(ProjectCategory.objects.filter(pk=self.category.pk).exists())
        self.assertTrue(Technology.objects.filter(pk=self.technology.pk).exists())
        self.assertTrue(ProjectType.objects.filter(pk=self.project_type.pk).exists())
        self.assertTrue(FooterLink.objects.filter(pk=self.footer.pk).exists())
        self.assertFalse(AuditLog.objects.filter(pk=self.audit_log.pk).exists())
        self.assertFalse(
            import_module(settings.SESSION_ENGINE).SessionStore(
                session_key=self.demo_session_key
            ).exists(self.demo_session_key)
        )
        self.assertIn('Demo/test verisi transaction.atomic içinde silindi', output.getvalue())

    def test_unexpected_failure_rolls_back_confirmed_cleanup(self):
        original_delete = Command._delete_queryset
        calls = 0

        def fail_after_first_delete(queryset, totals):
            nonlocal calls
            original_delete(queryset, totals)
            calls += 1
            if calls == 2:
                raise RuntimeError('beklenen test hatası')

        with patch.object(Command, '_delete_queryset', side_effect=fail_after_first_delete):
            with self.assertRaisesRegex(RuntimeError, 'beklenen test hatası'):
                call_command('cleanup_demo_data', confirm=True, no_color=True)

        self.assertTrue(User.objects.filter(pk=self.demo_student.pk).exists())
        self.assertTrue(ConsentRecord.objects.filter(user_id=self.demo_student.pk).exists())
        self.assertTrue(Project.objects.filter(pk=self.demo_project.pk).exists())
