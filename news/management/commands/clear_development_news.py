import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from news.models import Article


class Command(BaseCommand):
    help = 'DEBUG SQLite ortamında Article kayıtlarını yedek alarak güvenle temizler.'

    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true', help='Silme işlemini açıkça onaylar.')

    def handle(self, *args, **options):
        if not options['confirm']:
            raise CommandError('İşlem için --confirm parametresi zorunludur.')
        if not settings.DEBUG:
            raise CommandError('Bu komut DEBUG=False ortamında çalışmaz.')
        if connection.vendor != 'sqlite':
            raise CommandError('Bu komut yalnızca SQLite geliştirme veritabanında çalışır.')

        source_path = Path(settings.DATABASES['default']['NAME']).resolve()
        if not source_path.is_file():
            raise CommandError(f'SQLite veritabanı bulunamadı: {source_path}')
        backup_dir = Path(settings.BASE_DIR) / 'backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup_path = backup_dir / f'pre-news-clear-{stamp}.sqlite3'
        connection.close()
        with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as destination:
            source.backup(destination)
        with transaction.atomic():
            count = Article.objects.count()
            Article.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f'Yedek: {backup_path}'))
        self.stdout.write(self.style.SUCCESS(f'Silinen Article sayısı: {count}'))
