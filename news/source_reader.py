import ipaddress
import re
import socket
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests


MAX_REDIRECTS = 3
MAX_CONTENT_BYTES = 1_000_000
ALLOWED_CONTENT_TYPES = {'text/html', 'application/xhtml+xml'}


class SourceReadError(Exception):
    pass


def validate_public_url(url):
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise SourceReadError('Kaynak adresi geçersiz.') from exc
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise SourceReadError('Yalnızca geçerli HTTP ve HTTPS adresleri okunabilir.')
    if parsed.username or parsed.password:
        raise SourceReadError('Kullanıcı bilgisi içeren kaynak adresleri okunamaz.')
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
    except (socket.gaierror, OSError) as exc:
        raise SourceReadError('Kaynak adresinin sunucusu çözümlenemedi.') from exc
    if not addresses:
        raise SourceReadError('Kaynak adresinin sunucusu çözümlenemedi.')
    for item in addresses:
        ip = ipaddress.ip_address(item[4][0].split('%', 1)[0])
        if not ip.is_global:
            raise SourceReadError('Yerel veya özel ağ adresleri güvenlik nedeniyle okunamaz.')
    return url


class _ReadableHTMLParser(HTMLParser):
    BLOCKED = {'script', 'style', 'iframe', 'noscript', 'svg', 'canvas', 'form'}
    CONTENT = {'article', 'main', 'p', 'h1', 'h2', 'h3', 'li', 'blockquote'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocked_depth = 0
        self.content_depth = 0
        self.in_title = False
        self.title_parts = []
        self.content_parts = []
        self.fallback_parts = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.BLOCKED:
            self.blocked_depth += 1
        if not self.blocked_depth and tag in self.CONTENT:
            self.content_depth += 1
        if not self.blocked_depth and tag == 'title':
            self.in_title = True

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.BLOCKED and self.blocked_depth:
            self.blocked_depth -= 1
            return
        if not self.blocked_depth and tag in self.CONTENT and self.content_depth:
            self.content_depth -= 1
            self.content_parts.append('\n')
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.blocked_depth:
            return
        cleaned = re.sub(r'\s+', ' ', unescape(data)).strip()
        if not cleaned:
            return
        if self.in_title:
            self.title_parts.append(cleaned)
        self.fallback_parts.append(cleaned)
        if self.content_depth:
            self.content_parts.append(cleaned)

    def result(self):
        title = ' '.join(self.title_parts).strip()
        parts = self.content_parts or self.fallback_parts
        content = re.sub(r'\n{3,}', '\n\n', ' '.join(parts).replace(' \n ', '\n')).strip()
        return title[:300], content[:20_000]


def read_source(url, session=None):
    session = session or requests.Session()
    current = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        validate_public_url(current)
        try:
            response = session.get(
                current,
                allow_redirects=False,
                stream=True,
                timeout=(3, 5),
                headers={'User-Agent': 'BST-Portal-Source-Preview/1.0'},
            )
        except requests.Timeout as exc:
            raise SourceReadError('Kaynak zaman aşımına uğradı. Lütfen tekrar deneyin.') from exc
        except requests.RequestException as exc:
            raise SourceReadError('Kaynağa bağlanılamadı.') from exc

        try:
            if response.is_redirect or response.is_permanent_redirect:
                if redirect_count >= MAX_REDIRECTS:
                    raise SourceReadError('Kaynak çok fazla yönlendirme yaptı.')
                location = response.headers.get('Location')
                if not location:
                    raise SourceReadError('Kaynağın yönlendirme adresi geçersiz.')
                current = urljoin(current, location)
                continue
            if response.status_code >= 400:
                raise SourceReadError(f'Kaynak {response.status_code} durum kodu döndürdü.')
            content_type = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
            if content_type not in ALLOWED_CONTENT_TYPES:
                raise SourceReadError('Kaynak okunabilir bir HTML sayfası değil.')
            declared_size = response.headers.get('Content-Length')
            if declared_size:
                try:
                    declared_size = int(declared_size)
                except (TypeError, ValueError):
                    declared_size = None
                if declared_size is not None and declared_size > MAX_CONTENT_BYTES:
                    raise SourceReadError('Kaynak içeriği önizleme sınırından büyük.')
            chunks = []
            size = 0
            for chunk in response.iter_content(16_384):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_CONTENT_BYTES:
                    raise SourceReadError('Kaynak içeriği önizleme sınırından büyük.')
                chunks.append(chunk)
            encoding = response.encoding or 'utf-8'
            html = b''.join(chunks).decode(encoding, errors='replace')
        finally:
            response.close()

        parser = _ReadableHTMLParser()
        parser.feed(html)
        title, content = parser.result()
        if len(content) < 40:
            raise SourceReadError('Kaynak otomatik olarak okunamadı. Kaynağa Git seçeneğini kullanabilirsiniz.')
        return {'title': title, 'content': content, 'url': current}
    raise SourceReadError('Kaynak okunamadı.')
