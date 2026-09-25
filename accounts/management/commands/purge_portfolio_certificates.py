"""Manually remove portfolio certificates after an explicit operator decision."""

import logging

from django.core.management.base import BaseCommand
from django.db import models, transaction

from accounts.models import PortfolioCertificate

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Sertifika kayıtlarını sayar; yalnız --confirm ile kalıcı olarak siler.'

    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true', help='Kalıcı silmeyi açıkça onayla')

    def handle(self, *args, **options):
        count = PortfolioCertificate.objects.count()
        self.stdout.write(f'{count} sertifika kaydı bulundu.')
        if not options['confirm']:
            self.stdout.write('Dry-run: hiçbir kayıt silinmedi. Silmek için --confirm gerekir.')
            return
        files = []
        with transaction.atomic():
            for certificate in PortfolioCertificate.objects.select_for_update().iterator():
                for field in certificate._meta.fields:
                    if isinstance(field, models.FileField):
                        value = getattr(certificate, field.name)
                        if value and value.name:
                            files.append((value.storage, value.name))
            PortfolioCertificate.objects.all().delete()
            def remove_files():
                for storage, name in set(files):
                    try:
                        storage.delete(name)
                    except Exception:
                        logger.exception('Sertifika dosyası silinemedi: %s', name)

            transaction.on_commit(remove_files)
        self.stdout.write(self.style.SUCCESS(f'{count} sertifika kaydı silindi.'))
