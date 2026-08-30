from collections import Counter

from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError, RestrictedError

from accounts.models import (
    ConsentRecord,
    DataSubjectRequest,
    EmailVerification,
    UserModerationAction,
    UserReport,
    WebsiteModerationHistory,
)
from ai_assistant.models import ChatCache, KnowledgeSource
from alumni.models import Alumni, AlumniRegistrationRequest
from career.models import CollaborationRequest, MentorshipRequest, Opportunity
from core.models import AnalyticsEvent, AuditLog, Notification
from events.models import Event, EventRegistration
from news.models import Article
from projects.models import (
    Project,
    ProjectComment,
    ProjectContribution,
    ProjectFeedback,
    ProjectLike,
    ProjectRequest,
    ProjectRequestApplication,
    ProjectSave,
    ProjectUpdate,
    ProjectWritingSuggestion,
    Team,
    TeamInvitation,
    TeamMembership,
)


class Command(BaseCommand):
    help = (
        'Açık test/demo işaretlerine sahip hesapları ve ilişkili demo içeriğini '
        'önce geri alınan bir transaction içinde raporlar; yalnızca --confirm ile kalıcı siler.'
    )

    DEFAULT_EMAIL_DOMAINS = ('example.com', 'example.test', 'test.local')
    DEFAULT_USERNAME_PREFIXES = ('test-', 'test_', 'demo-', 'demo_', 'audit-', 'audit_')
    DEFAULT_EXACT_USERNAMES = ('testuser',)
    DEFAULT_CONTENT_MARKERS = ('[DEMO]', '[TEST]', 'DEMO:', 'TEST:')
    DELETABLE_ROLES = ('student', 'visitor', 'approved_member')

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            '--dry-run',
            action='store_true',
            help='Silme planını çalıştırır, sayımları gösterir ve transactionı geri alır (varsayılan).',
        )
        mode.add_argument(
            '--confirm',
            action='store_true',
            help='Aynı planı transaction.atomic içinde kalıcı olarak uygular.',
        )
        parser.add_argument(
            '--user-id',
            action='append',
            type=int,
            default=[],
            metavar='ID',
            help='Varsayılan işaretlere ek olarak hedeflenecek kullanıcı IDsi; birden fazla verilebilir.',
        )
        parser.add_argument(
            '--username',
            action='append',
            default=[],
            metavar='USERNAME',
            help='Varsayılan işaretlere ek olarak hedeflenecek tam kullanıcı adı; birden fazla verilebilir.',
        )
        parser.add_argument(
            '--email-domain',
            action='append',
            default=[],
            metavar='DOMAIN',
            help='Varsayılan test alan adlarına ek alan adı; @ işareti olmadan birden fazla verilebilir.',
        )
        parser.add_argument(
            '--content-marker',
            action='append',
            default=[],
            metavar='PREFIX',
            help='Bağımsız demo içerik başlık/adları için ek önek; birden fazla verilebilir.',
        )

    def handle(self, *args, **options):
        confirm = options['confirm']
        domains = self._domains(options['email_domain'])
        exact_usernames = self._nonempty(
            (*self.DEFAULT_EXACT_USERNAMES, *options['username']), 'Kullanıcı adı'
        )
        markers = self._nonempty(
            (*self.DEFAULT_CONTENT_MARKERS, *options['content_marker']), 'İçerik işareti'
        )
        user_ids = set(options['user_id'])
        if any(user_id <= 0 for user_id in user_ids):
            raise CommandError('Kullanıcı ID değerleri pozitif olmalıdır.')

        marker_query = self._account_marker_query(domains, exact_usernames, user_ids)

        try:
            with transaction.atomic():
                marked_users = list(
                    User.objects.select_for_update()
                    .select_related('profile')
                    .filter(marker_query)
                    .order_by('pk')
                )
                target_users, protected_users = self._partition_users(marked_users)
                target_ids = {user.pk for user in target_users}
                target_emails = {user.email.lower() for user in target_users if user.email}

                self._write_scope(target_users, protected_users, domains, markers, confirm)
                totals = self._delete_plan(target_ids, target_emails, domains, markers)

                if not confirm:
                    transaction.set_rollback(True)

        except (ProtectedError, RestrictedError) as exc:
            raise CommandError(
                'Silme planı korunan bir ilişki nedeniyle durduruldu; hiçbir değişiklik kaydedilmedi. '
                f'Ayrıntı: {exc}'
            ) from exc

        self._write_totals(totals, confirm)

    def _domains(self, extra_domains):
        domains = []
        for raw_domain in (*self.DEFAULT_EMAIL_DOMAINS, *extra_domains):
            domain = raw_domain.strip().lower().lstrip('@')
            if not domain or any(char.isspace() for char in domain) or '.' not in domain:
                raise CommandError(f'Geçersiz e-posta alan adı: {raw_domain!r}')
            if domain not in domains:
                domains.append(domain)
        return tuple(domains)

    @staticmethod
    def _nonempty(values, label):
        cleaned = []
        for raw_value in values:
            value = raw_value.strip()
            if not value:
                raise CommandError(f'{label} boş olamaz.')
            if value not in cleaned:
                cleaned.append(value)
        return tuple(cleaned)

    def _account_marker_query(self, domains, exact_usernames, user_ids):
        query = Q(pk__in=user_ids)
        for username in exact_usernames:
            query |= Q(username__iexact=username)
        for prefix in self.DEFAULT_USERNAME_PREFIXES:
            query |= Q(username__istartswith=prefix)
        for domain in domains:
            query |= Q(email__iendswith=f'@{domain}')
        return query

    def _partition_users(self, users):
        targets = []
        protected = []
        alumni_user_ids = set(
            Alumni.objects.filter(user_id__in=[user.pk for user in users]).values_list('user_id', flat=True)
        )

        for user in users:
            profile = getattr(user, 'profile', None)
            role = profile.user_type if profile else None
            reasons = []
            if user.is_superuser:
                reasons.append('superuser')
            if user.is_staff:
                reasons.append('is_staff/admin')
            if role not in self.DELETABLE_ROLES:
                reasons.append(f'korunan veya tanımsız rol: {role or "profil yok"}')
            if user.pk in alumni_user_ids:
                reasons.append('Alumni kaydına bağlı')

            if reasons:
                protected.append((user, ', '.join(reasons)))
            else:
                targets.append(user)
        return targets, protected

    def _write_scope(self, targets, protected, domains, markers, confirm):
        mode = 'KALICI SİLME' if confirm else 'DRY-RUN (transaction geri alınacak)'
        self.stdout.write(self.style.WARNING(f'Mod: {mode}'))
        self.stdout.write(f'Test e-posta alan adları: {", ".join(domains)}')
        self.stdout.write(f'Demo içerik önekleri: {", ".join(markers)}')
        self.stdout.write('')
        self.stdout.write(f'Hedef demo hesapları ({len(targets)}):')
        if targets:
            for user in targets:
                role = getattr(getattr(user, 'profile', None), 'user_type', 'profil yok')
                self.stdout.write(f'  - id={user.pk} username={user.username!r} email={user.email!r} rol={role}')
        else:
            self.stdout.write('  - yok')

        self.stdout.write(f'Korundu / atlandı ({len(protected)}):')
        if protected:
            for user, reason in protected:
                self.stdout.write(f'  - id={user.pk} username={user.username!r}: {reason}')
        else:
            self.stdout.write('  - yok')
        self.stdout.write('')

    def _delete_plan(self, user_ids, target_emails, domains, markers):
        totals = Counter()

        project_ids = set(
            Project.objects.filter(
                Q(created_by_id__in=user_ids) | self._prefix_query(('title',), markers)
            ).values_list('pk', flat=True)
        )
        team_ids = set(
            Team.objects.filter(
                Q(leader_id__in=user_ids) | self._prefix_query(('name',), markers)
            ).values_list('pk', flat=True)
        )
        request_ids = set(
            ProjectRequest.objects.filter(
                Q(teacher_id__in=user_ids) | self._prefix_query(('title',), markers)
            ).values_list('pk', flat=True)
        )
        event_ids = set(
            Event.objects.filter(
                Q(created_by_id__in=user_ids) | self._prefix_query(('title',), markers)
            ).values_list('pk', flat=True)
        )
        article_ids = set(
            Article.objects.filter(
                Q(created_by_id__in=user_ids)
                | self._prefix_query(('title',), markers)
                | Q(
                    source__in=('TechDemo', 'UniDemo', 'SectorDemo'),
                    source_url__istartswith='https://example.com/',
                )
            ).values_list('pk', flat=True)
        )
        opportunity_ids = set(
            Opportunity.objects.filter(
                Q(created_by_id__in=user_ids)
                | self._prefix_query(('title', 'organization'), markers)
                | self._domain_query(('contact_email',), domains)
            ).values_list('pk', flat=True)
        )
        collaboration_ids = set(
            CollaborationRequest.objects.filter(
                self._prefix_query(('title', 'organization'), markers)
                | self._domain_query(('email',), domains)
            ).values_list('pk', flat=True)
        )
        knowledge_ids = set(
            KnowledgeSource.objects.filter(
                Q(created_by_id__in=user_ids) | self._prefix_query(('title',), markers)
            ).values_list('pk', flat=True)
        )
        profile_ids = set(
            User.objects.filter(pk__in=user_ids).values_list('profile__pk', flat=True)
        ) - {None}

        session_ids = []
        if user_ids:
            for session in Session.objects.all().only('session_key', 'session_data'):
                try:
                    session_user_id = int(session.get_decoded().get('_auth_user_id', 0))
                except (TypeError, ValueError):
                    continue
                if session_user_id in user_ids:
                    session_ids.append(session.session_key)

        # Explicitly remove PROTECT relations before deleting the selected users/profiles.
        protected_relations = (
            WebsiteModerationHistory.objects.filter(
                Q(profile_id__in=profile_ids) | Q(performed_by_id__in=user_ids)
            ),
            UserModerationAction.objects.filter(
                Q(user_id__in=user_ids) | Q(performed_by_id__in=user_ids)
            ),
            UserReport.objects.filter(
                Q(reporter_id__in=user_ids) | Q(reported_user_id__in=user_ids)
            ),
            AlumniRegistrationRequest.objects.filter(
                Q(user_id__in=user_ids) | Q(reviewed_by_id__in=user_ids)
            ),
            ConsentRecord.objects.filter(user_id__in=user_ids),
            DataSubjectRequest.objects.filter(user_id__in=user_ids),
            TeamInvitation.objects.filter(
                Q(invited_user_id__in=user_ids) | Q(invited_by_id__in=user_ids)
            ),
        )
        for queryset in protected_relations:
            self._delete_queryset(queryset, totals)

        user_activity = (
            Notification.objects.filter(Q(recipient_id__in=user_ids) | Q(actor_id__in=user_ids)),
            EventRegistration.objects.filter(Q(user_id__in=user_ids) | Q(event_id__in=event_ids)),
            ProjectComment.objects.filter(author_id__in=user_ids),
            ProjectLike.objects.filter(user_id__in=user_ids),
            ProjectSave.objects.filter(user_id__in=user_ids),
            ProjectContribution.objects.filter(user_id__in=user_ids),
            ProjectWritingSuggestion.objects.filter(created_by_id__in=user_ids),
            ProjectFeedback.objects.filter(teacher_id__in=user_ids),
            ProjectUpdate.objects.filter(created_by_id__in=user_ids),
            ProjectRequestApplication.objects.filter(
                Q(student_id__in=user_ids) | Q(project_request_id__in=request_ids)
            ),
            TeamMembership.objects.filter(Q(user_id__in=user_ids) | Q(team_id__in=team_ids)),
            MentorshipRequest.objects.filter(student_id__in=user_ids),
            Session.objects.filter(session_key__in=session_ids),
            EmailVerification.objects.filter(self._email_query('email', target_emails)),
        )
        for queryset in user_activity:
            self._delete_queryset(queryset, totals)

        analytics_query = (
            Q(target_type='projects.project', target_id__in={str(pk) for pk in project_ids})
            | Q(target_type='events.event', target_id__in={str(pk) for pk in event_ids})
            | Q(target_type='accounts.profile', target_id__in={str(pk) for pk in profile_ids})
        )
        self._delete_queryset(AnalyticsEvent.objects.filter(analytics_query), totals)

        audit_query = Q(actor_id__in=user_ids)
        audit_targets = (
            ('auth.user', user_ids),
            ('accounts.profile', profile_ids),
            ('projects.project', project_ids),
            ('projects.projectrequest', request_ids),
            ('projects.team', team_ids),
            ('events.event', event_ids),
            ('news.article', article_ids),
            ('career.opportunity', opportunity_ids),
            ('career.collaborationrequest', collaboration_ids),
            ('ai_assistant.knowledgesource', knowledge_ids),
        )
        for target_type, target_ids in audit_targets:
            audit_query |= Q(
                target_type=target_type,
                target_id__in={str(pk) for pk in target_ids},
            )
        self._delete_queryset(AuditLog.objects.filter(audit_query), totals)

        content_querysets = (
            Project.objects.filter(pk__in=project_ids),
            ProjectRequest.objects.filter(pk__in=request_ids),
            Team.objects.filter(pk__in=team_ids),
            Event.objects.filter(pk__in=event_ids),
            Article.objects.filter(pk__in=article_ids),
            Opportunity.objects.filter(pk__in=opportunity_ids),
            CollaborationRequest.objects.filter(pk__in=collaboration_ids),
            KnowledgeSource.objects.filter(pk__in=knowledge_ids),
        )
        for queryset in content_querysets:
            self._delete_queryset(queryset, totals)

        if knowledge_ids:
            # AI cevap önbelleği türetilmiş veridir; kaynak kümesi değişince tamamı geçersiz olur.
            self._delete_queryset(ChatCache.objects.all(), totals)

        self._delete_queryset(User.objects.filter(pk__in=user_ids), totals)
        return totals

    @staticmethod
    def _delete_queryset(queryset, totals):
        _, breakdown = queryset.delete()
        totals.update(breakdown)

    @staticmethod
    def _prefix_query(fields, markers):
        query = Q(pk__in=[])
        for field in fields:
            for marker in markers:
                query |= Q(**{f'{field}__istartswith': marker})
        return query

    @staticmethod
    def _domain_query(fields, domains):
        query = Q(pk__in=[])
        for field in fields:
            for domain in domains:
                query |= Q(**{f'{field}__iendswith': f'@{domain}'})
        return query

    @staticmethod
    def _email_query(field, emails):
        query = Q(pk__in=[])
        for email in emails:
            query |= Q(**{f'{field}__iexact': email})
        return query

    def _write_totals(self, totals, confirm):
        heading = 'Silinen kayıtlar' if confirm else 'Silinecek kayıtlar'
        self.stdout.write(f'{heading} (cascade dahil):')
        if totals:
            for model_label, count in sorted(totals.items()):
                self.stdout.write(f'  - {model_label}: {count}')
            self.stdout.write(f'  TOPLAM: {sum(totals.values())}')
        else:
            self.stdout.write('  - yok')

        if confirm:
            self.stdout.write(self.style.SUCCESS('Demo/test verisi transaction.atomic içinde silindi.'))
        else:
            self.stdout.write(self.style.SUCCESS('Dry-run tamamlandı; transaction geri alındı, veri değişmedi.'))
            self.stdout.write('Kalıcı uygulama için çıktıyı kontrol edip komutu --confirm ile yeniden çalıştırın.')
        self.stdout.write('Not: Veritabanı dışındaki yüklenmiş medya dosyalarına dokunulmadı.')
