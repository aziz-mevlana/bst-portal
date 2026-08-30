"""Prepare or serve the isolated preview; never modify the source database."""
import os
import shutil
import sqlite3
import sys

os.environ['DJANGO_SETTINGS_MODULE'] = 'bst_portal.preview_settings'


def main():
    import django
    django.setup()
    from django.conf import settings
    from django.core.management import call_command

    if '--prepare' in sys.argv:
        target = settings.DATABASES['default']['NAME']
        source = settings.SOURCE_DATABASE_PATH
        if not target.exists() and source.exists():
            with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as original:
                with sqlite3.connect(target) as preview:
                    original.backup(preview)
            print('Created isolated database copy.', flush=True)
        if not settings.MEDIA_ROOT.exists():
            if settings.SOURCE_MEDIA_ROOT.exists():
                shutil.copytree(settings.SOURCE_MEDIA_ROOT, settings.MEDIA_ROOT)
            else:
                settings.MEDIA_ROOT.mkdir(parents=True)
        call_command('migrate', interactive=False)
        call_command('collectstatic', interactive=False, verbosity=0)
        call_command('check')
        print('Preview prepared.', flush=True)
        return

    from django.core.wsgi import get_wsgi_application
    from waitress import serve
    print('Preview server listening on 127.0.0.1:8765', flush=True)
    serve(
        get_wsgi_application(),
        host='127.0.0.1', port=8765, threads=8,
        trusted_proxy='127.0.0.1', trusted_proxy_count=1,
        trusted_proxy_headers={'x-forwarded-for', 'x-forwarded-proto'},
        clear_untrusted_proxy_headers=True,
        max_request_body_size=30 * 1024 * 1024,
    )


if __name__ == '__main__':
    main()
