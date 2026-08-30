from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .audit import record_audit_event
from .rate_limit import is_rate_limited
from .models import Notification


class FooterManagementTests(TestCase):
    def setUp(self):
        from .models import FooterLink
        self.admin = User.objects.create_superuser('footer-admin', 'admin@example.com', 'StrongPassword123!')
        self.link = FooterLink.objects.get(section='contributors', label='Oğuzhan Bodur')
        self.url = reverse('dashboard:footer_settings')

    def payload(self, **changes):
        from .models import FooterLink
        links = list(FooterLink.objects.all())
        data = {'links-TOTAL_FORMS': len(links), 'links-INITIAL_FORMS': len(links)}
        for index, link in enumerate(links):
            values = {'id': link.pk, 'label': link.label, 'section': link.section, 'url': link.url,
                      'sort_order': link.sort_order, 'is_active': link.is_active, 'open_new_tab': link.open_new_tab}
            if link.pk == self.link.pk:
                values.update(changes)
            data.update({f'links-{index}-{key}': value for key, value in values.items()})
        return data

    def test_only_admin_can_manage_footer(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        authority = User.objects.create_user('footer-authority')
        authority.profile.user_type = 'staff_student'
        authority.profile.save()
        self.client.force_login(authority)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, self.payload(label='Forbidden')).status_code, 403)
        self.link.refresh_from_db()
        self.assertEqual(self.link.label, 'Oğuzhan Bodur')

    def test_admin_update_appears_in_footer_and_is_audited(self):
        from .models import AuditLog
        self.client.force_login(self.admin)
        response = self.client.post(self.url, self.payload(label='Oğuzhan · Geliştirici'))
        self.assertRedirects(response, self.url)
        page = self.client.get(reverse('portal:index'))
        self.assertContains(page, 'Oğuzhan · Geliştirici')
        self.assertContains(page, 'https://www.linkedin.com/in/oguzhan-bodur/')
        self.assertContains(page, 'Katkıda Bulunanlar')
        self.assertContains(page, 'Mevlana')
        self.assertNotContains(page, 'Made By')
        self.assertTrue(AuditLog.objects.filter(action='site.footer_updated', actor=self.admin).exists())

    def test_footer_uses_four_column_main_area_and_contributors_are_last(self):
        page = self.client.get(reverse('portal:index'))
        html = page.content.decode()
        self.assertContains(page, 'class="footer-brand"')
        self.assertEqual(html.count('class="footer-column"'), 3)
        self.assertContains(page, 'class="footer-contributors-title"')
        self.assertContains(page, 'class="footer-contributors-list"')
        self.assertGreater(html.index('class="footer-contributors"'), html.index('class="footer-bottom"'))

    def test_unsafe_links_rejected_without_partial_updates(self):
        self.client.force_login(self.admin)
        for url in ['javascript:alert(1)', '//evil.example/path', '/\\evil.example', 'https://[bad', 'mailto:a@example.com?body=x', 'https://localhost/']:
            with self.subTest(url=url):
                response = self.client.post(self.url, self.payload(label='Should not save', url=url))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['formset'].errors)
                self.link.refresh_from_db()
                self.assertEqual(self.link.label, 'Oğuzhan Bodur')

    def test_inactive_link_hidden_and_delete_persists(self):
        self.client.force_login(self.admin)
        self.client.post(self.url, self.payload(is_active=False))
        self.assertNotContains(self.client.get(reverse('portal:index')), self.link.url)
        self.client.post(self.url, self.payload(DELETE=True))
        from .models import FooterLink
        self.assertFalse(FooterLink.objects.filter(pk=self.link.pk).exists())

    def test_admin_can_add_link_and_missing_management_form_is_rejected(self):
        from .models import FooterLink
        self.client.force_login(self.admin)
        data = self.payload()
        index = data['links-TOTAL_FORMS']
        data['links-TOTAL_FORMS'] = index + 1
        data.update({f'links-{index}-{key}': value for key, value in {
            'section': 'navigation', 'label': 'Yetenekler', 'url': '/talent/', 'sort_order': 20, 'is_active': True,
        }.items()})
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.assertTrue(FooterLink.objects.filter(label='Yetenekler', url='/talent/').exists())
        count = FooterLink.objects.count()
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['formset'].non_form_errors())
        self.assertEqual(FooterLink.objects.count(), count)


class HealthCheckTests(TestCase):
    def test_health_endpoint_checks_database_and_cache(self):
        response = self.client.get(reverse('health_check'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        self.assertEqual(response.json()['checks'], {'database': True, 'cache': True})

    def test_robots_and_private_page_metadata(self):
        robots = self.client.get(reverse('robots_txt'))
        self.assertEqual(robots.status_code, 200)
        self.assertContains(robots, 'Sitemap: http://testserver/sitemap.xml')
        login = self.client.get(reverse('accounts:login'))
        self.assertContains(login, 'content="noindex,nofollow"')

    def test_dynamic_pages_receive_security_headers(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertIn("object-src 'none'", response['Content-Security-Policy'])
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertIn('camera=()', response['Permissions-Policy'])


class CloudflarePreviewTests(SimpleTestCase):
    @override_settings(ALLOWED_HOSTS=['testserver'])
    def test_preview_rejects_invalid_host_before_rendering_error_templates(self):
        from bst_portal.preview import PreviewHeadersMiddleware

        def unexpected(request):
            self.fail('Invalid host reached the application')

        response = PreviewHeadersMiddleware(unexpected)(
            RequestFactory().get('/', HTTP_HOST='attacker.invalid')
        )
        self.assertEqual(response.status_code, 400)

    def test_preview_blocks_search_indexing(self):
        from bst_portal.preview import PreviewHeadersMiddleware
        from django.http import HttpResponse

        middleware = PreviewHeadersMiddleware(lambda request: HttpResponse('page'))
        response = middleware(RequestFactory().get('/robots.txt'))
        self.assertEqual(response.content, b'User-agent: *\nDisallow: /\n')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow, noarchive')

    def test_preview_media_rejects_paths_outside_media_root(self):
        from bst_portal.preview import preview_media
        from django.http import Http404
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            root = Path(directory) / 'media'
            root.mkdir()
            (Path(directory) / 'private.txt').write_text('private')
            with override_settings(MEDIA_ROOT=root):
                with self.assertRaises(Http404):
                    preview_media(RequestFactory().get('/media/'), '../private.txt')

    def test_preview_media_downloads_active_content(self):
        from bst_portal.preview import preview_media
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            (Path(directory) / 'upload.html').write_text('<script>alert(1)</script>')
            with override_settings(MEDIA_ROOT=directory):
                response = preview_media(RequestFactory().get('/media/upload.html'), 'upload.html')
                try:
                    self.assertTrue(response['Content-Disposition'].startswith('attachment;'))
                    self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
                    self.assertIn('sandbox', response['Content-Security-Policy'])
                finally:
                    response.close()


class AuditAndRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def test_audit_log_is_immutable_and_hashes_client_address(self):
        actor = User.objects.create_user('auditor', 'auditor@example.com', 'StrongPassword123!')
        request = self.factory.post('/critical/')
        request.user = actor
        request.META['REMOTE_ADDR'] = '203.0.113.7'
        event = record_audit_event(
            actor=actor,
            action='test.critical_action',
            target=actor,
            request=request,
        )
        self.assertEqual(len(event.client_hash), 64)
        self.assertNotIn('203.0.113.7', event.client_hash)
        event.action = 'tampered'
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()

    def test_rate_limit_uses_fixed_window(self):
        request = self.factory.post('/login/')
        request.user = AnonymousUser()
        request.META['REMOTE_ADDR'] = '198.51.100.5'
        self.assertFalse(is_rate_limited(request, scope='test', limit=2, window_seconds=60))
        self.assertFalse(is_rate_limited(request, scope='test', limit=2, window_seconds=60))
        self.assertTrue(is_rate_limited(request, scope='test', limit=2, window_seconds=60))

    @override_settings(TRUSTED_PROXY_IPS={'127.0.0.1'})
    def test_rate_limit_only_trusts_forwarded_ip_from_configured_proxy(self):
        proxied = self.factory.post('/login/', REMOTE_ADDR='127.0.0.1', HTTP_X_REAL_IP='198.51.100.10')
        proxied.user = AnonymousUser()
        direct = self.factory.post('/login/', REMOTE_ADDR='198.51.100.20', HTTP_X_REAL_IP='198.51.100.10')
        direct.user = AnonymousUser()

        self.assertFalse(is_rate_limited(proxied, scope='proxy', limit=1, window_seconds=60))
        self.assertTrue(is_rate_limited(proxied, scope='proxy', limit=1, window_seconds=60))
        self.assertFalse(is_rate_limited(direct, scope='proxy', limit=1, window_seconds=60))


class NotificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('recipient', password='StrongPassword123!')
        self.other = User.objects.create_user('other', password='StrongPassword123!')
        self.notification = Notification.objects.create(
            recipient=self.user,
            notification_type='system',
            message='Test bildirimi',
            target_url='/projects/',
        )

    def test_only_recipient_can_mark_notification_read_and_post_is_required(self):
        url = reverse('core:notification_mark_read', args=[self.notification.pk])
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(self.client.post(url), '/projects/')
        self.notification.refresh_from_db()
        self.assertIsNotNone(self.notification.read_at)

        self.notification.read_at = None
        self.notification.save(update_fields=['read_at'])
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_external_notification_target_is_rejected(self):
        with self.assertRaises(ValidationError):
            Notification.objects.create(
                recipient=self.user,
                notification_type='system',
                message='Güvensiz hedef',
                target_url='https://example.com/phishing',
            )
