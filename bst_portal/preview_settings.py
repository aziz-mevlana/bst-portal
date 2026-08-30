"""Isolated settings for a temporary Cloudflare test session only."""
import os
import re
import secrets
from pathlib import Path

PREVIEW_DIR = Path(__file__).resolve().parent.parent / '.preview'
PREVIEW_DIR.mkdir(exist_ok=True)
secret_file = PREVIEW_DIR / 'secret.key'
if not secret_file.exists():
    secret_file.write_text(secrets.token_urlsafe(64), encoding='utf-8')

# Override local development values before importing the normal settings.
os.environ['DJANGO_DEBUG'] = 'False'
os.environ['DJANGO_ISOLATED_PREVIEW'] = 'True'
os.environ['DJANGO_SECRET_KEY'] = secret_file.read_text(encoding='utf-8').strip()
os.environ['DJANGO_SECURE_SSL_REDIRECT'] = 'True'
os.environ['USE_S3'] = 'False'

from .settings import *  # noqa: F403,E402

SOURCE_DATABASE_PATH = DATABASES['default']['NAME']
SOURCE_MEDIA_ROOT = MEDIA_ROOT
DATABASES['default']['NAME'] = PREVIEW_DIR / 'db.sqlite3'
MEDIA_ROOT = PREVIEW_DIR / 'media'
ROOT_URLCONF = 'bst_portal.preview'
MIDDLEWARE = ['bst_portal.preview.PreviewHeadersMiddleware', *MIDDLEWARE]
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver']
CSRF_TRUSTED_ORIGINS = []
url_file = PREVIEW_DIR / 'url.txt'
if url_file.exists():
    preview_url = url_file.read_text(encoding='utf-8-sig').strip()
    if not re.fullmatch(r'https://[a-z0-9-]+\.trycloudflare\.com', preview_url):
        raise ImproperlyConfigured('Invalid Cloudflare preview URL.')
    ALLOWED_HOSTS.append(preview_url.removeprefix('https://'))
    CSRF_TRUSTED_ORIGINS = [preview_url]

# This hostname is temporary; do not persist an HSTS policy in testers' browsers.
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_PRELOAD = False
SESSION_COOKIE_NAME = 'bst_preview_sessionid'
CSRF_COOKIE_NAME = 'bst_preview_csrftoken'
# Keep preview throttling and tasks independent of any local Redis service.
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'
