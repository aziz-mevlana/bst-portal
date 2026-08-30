from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from unittest.mock import Mock, patch
import requests

from .models import Article
from .source_reader import SourceReadError, read_source


class NewsVisibilityTests(TestCase):
    def setUp(self):
        self.article = Article.objects.create(
            title='Bekleyen haber',
            summary='Özet',
            content='İçerik',
            is_approved=False,
        )

    def test_unapproved_article_is_hidden_from_public(self):
        response = self.client.get(reverse('news:news_detail', args=[self.article.pk]))
        self.assertRedirects(response, reverse('news:news_list'))

    def test_staff_can_preview_unapproved_article(self):
        staff = User.objects.create_user(
            'staff', 'staff@example.com', 'StrongPassword123!', is_staff=True
        )
        self.client.force_login(staff)
        response = self.client.get(reverse('news:news_detail', args=[self.article.pk]))
        self.assertEqual(response.status_code, 200)

    def test_approved_article_is_public_and_uses_seo_url(self):
        self.article.is_approved = True
        self.article.save()
        response = self.client.get(self.article.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.article.title)


class _FakeResponse:
    def __init__(self, body=b'', status=200, content_type='text/html; charset=utf-8', location=None, content_length=None):
        self.body = body
        self.status_code = status
        self.headers = {'Content-Type': content_type}
        if location:
            self.headers['Location'] = location
        if content_length is not None:
            self.headers['Content-Length'] = content_length
        self.encoding = 'utf-8'
        self.is_redirect = status in {301, 302, 303, 307, 308}
        self.is_permanent_redirect = status in {301, 308}

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        pass


class SourceReaderTests(TestCase):
    public_dns = [('AF', 'SOCK', 6, '', ('93.184.216.34', 443))]

    @patch('news.source_reader.socket.getaddrinfo')
    def test_safe_html_is_returned_as_plain_text(self, resolve):
        resolve.return_value = self.public_dns
        session = Mock()
        session.get.return_value = _FakeResponse(
            b'<html><title>Kaynak Basligi</title><article><h1>Haber</h1><p>Guvenli ve yeterince uzun haber metni burada yer aliyor.</p><script>alert(1)</script></article></html>'
        )
        result = read_source('https://example.com/news', session=session)
        self.assertEqual(result['title'], 'Kaynak Basligi')
        self.assertIn('Guvenli', result['content'])
        self.assertNotIn('alert', result['content'])
        self.assertNotIn('<script', result['content'])

    @patch('news.source_reader.socket.getaddrinfo')
    def test_private_ip_is_rejected(self, resolve):
        resolve.return_value = [('AF', 'SOCK', 6, '', ('127.0.0.1', 80))]
        with self.assertRaises(SourceReadError):
            read_source('http://localhost/private', session=Mock())

    @patch('news.source_reader.socket.getaddrinfo')
    def test_timeout_has_safe_turkish_error(self, resolve):
        resolve.return_value = self.public_dns
        session = Mock()
        session.get.side_effect = requests.Timeout()
        with self.assertRaisesRegex(SourceReadError, 'zaman aşımına'):
            read_source('https://example.com', session=session)

    @patch('news.source_reader.socket.getaddrinfo')
    def test_redirect_to_private_ip_is_rejected(self, resolve):
        resolve.side_effect = [
            self.public_dns,
            [('AF', 'SOCK', 6, '', ('10.0.0.2', 80))],
        ]
        session = Mock()
        session.get.return_value = _FakeResponse(status=302, location='http://10.0.0.2/private')
        with self.assertRaises(SourceReadError):
            read_source('https://example.com', session=session)

    @patch('news.source_reader.socket.getaddrinfo')
    def test_non_html_and_large_sources_are_rejected(self, resolve):
        resolve.return_value = self.public_dns
        session = Mock()
        session.get.return_value = _FakeResponse(b'pdf', content_type='application/pdf')
        with self.assertRaisesRegex(SourceReadError, 'HTML'):
            read_source('https://example.com/file', session=session)
        large = _FakeResponse(b'x' * 1_000_001)
        session.get.return_value = large
        with self.assertRaisesRegex(SourceReadError, 'sınırından büyük'):
            read_source('https://example.com/large', session=session)

    @patch('news.source_reader.socket.getaddrinfo')
    def test_malformed_content_length_does_not_crash_preview(self, resolve):
        resolve.return_value = self.public_dns
        session = Mock()
        session.get.return_value = _FakeResponse(
            b'<html><article><p>Gecersiz uzunluk basligina ragmen okunabilecek kadar uzun ve guvenli haber metni.</p></article></html>',
            content_length='gecersiz',
        )

        result = read_source('https://example.com/news', session=session)

        self.assertIn('Gecersiz uzunluk', result['content'])


class SourcePreviewPermissionTests(TestCase):
    def setUp(self):
        self.article = Article.objects.create(
            title='Kaynaklı haber', summary='Özet', content='İçerik',
            source_url='https://example.com/news-item',
        )
        self.staff = User.objects.create_user('news-admin', password='StrongPassword123!', is_staff=True)

    def test_anonymous_cannot_preview_source(self):
        response = self.client.get(reverse('dashboard:news_source_preview', args=[self.article.pk]))
        self.assertEqual(response.status_code, 302)

    @patch('news.source_reader.read_source')
    def test_staff_gets_sanitized_preview_payload(self, reader):
        reader.return_value = {'title': 'Okunan', 'content': 'Temiz içerik', 'url': self.article.source_url}
        self.client.force_login(self.staff)
        response = self.client.get(reverse('dashboard:news_source_preview', args=[self.article.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['content'], 'Temiz içerik')

    def test_dashboard_source_link_keeps_valid_hyphenated_url(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse('dashboard:news'))

        self.assertContains(response, 'data-source-url="https://example.com/news-item"')
        self.assertNotContains(response, r'\\u002D')
