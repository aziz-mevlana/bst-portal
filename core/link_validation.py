"""URLs rendered as public links must not accept executable schemes."""
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from accounts.validators import validate_public_website


def validate_footer_url(value):
    if any(ord(char) < 32 or char.isspace() for char in value) or '\\' in value:
        raise ValidationError('Bağlantıda boşluk veya kontrol karakteri olamaz.')
    if value.startswith('/') and not value.startswith('//'):
        return
    if value.startswith('mailto:'):
        validate_email(value[7:])
        return
    try:
        scheme = urlsplit(value).scheme
    except ValueError:
        raise ValidationError('Geçerli bir bağlantı girin.')
    if scheme not in {'http', 'https'}:
        raise ValidationError('Site içi /adres, https:// veya mailto: bağlantısı kullanın.')
    validate_public_website(value)
