import ipaddress
import re
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError


GITHUB_USERNAME_RE = re.compile(r'^(?!-)(?!.*--)[A-Za-z0-9-]{1,39}(?<!-)$')
LINKEDIN_SLUG_RE = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9-]{1,98}[A-Za-z0-9])?$')


def institutional_email_domain(email):
    normalized = (email or '').strip().casefold()
    if normalized.count('@') != 1:
        raise ValidationError('Geçerli bir kurumsal e-posta adresi girin.')
    local_part, domain = normalized.rsplit('@', 1)
    if not local_part or domain not in settings.INSTITUTIONAL_EMAIL_DOMAINS:
        allowed = ', '.join(f'@{item}' for item in sorted(settings.INSTITUTIONAL_EMAIL_DOMAINS))
        raise ValidationError(f'Öğrenci ve akademisyen kaydı için izin verilen kurumsal e-posta: {allowed}')
    return domain


def validate_github_username(value):
    value = (value or '').strip()
    if value and not GITHUB_USERNAME_RE.fullmatch(value):
        raise ValidationError(
            'Yalnızca GitHub kullanıcı adını girin; URL, eğik çizgi veya başka domain kullanmayın.'
        )


def validate_linkedin_slug(value):
    value = (value or '').strip()
    if value and not LINKEDIN_SLUG_RE.fullmatch(value):
        raise ValidationError(
            'Yalnızca LinkedIn profil kullanıcı adını girin; URL veya eğik çizgi kullanmayın.'
        )


def validate_public_website(value):
    value = (value or '').strip()
    if not value:
        return
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValidationError('Yalnızca güvenli bir HTTP/HTTPS web sitesi adresi girin.')
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValidationError('Web sitesi portu geçersiz.') from exc
    if port not in {None, 80, 443}:
        raise ValidationError('Kişisel web sitesi yalnızca standart HTTP/HTTPS portlarını kullanabilir.')
    hostname = parsed.hostname.rstrip('.').casefold()
    if hostname == 'localhost' or hostname.endswith(('.localhost', '.local')):
        raise ValidationError('Yerel ağ adresleri kişisel web sitesi olarak kullanılamaz.')
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if '.' not in hostname:
            raise ValidationError('Geçerli, herkese açık bir alan adı girin.')
    else:
        if not address.is_global:
            raise ValidationError('Özel veya ayrılmış IP adresleri kullanılamaz.')
