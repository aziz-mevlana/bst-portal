import csv
import secrets
import string
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


def generate_temporary_password():
    alphabet = string.ascii_letters + string.digits + '!@#$%&*'
    while True:
        password = ''.join(secrets.choice(alphabet) for _ in range(18))
        if (
            any(char.islower() for char in password)
            and any(char.isupper() for char in password)
            and any(char.isdigit() for char in password)
            and any(char in '!@#$%&*' for char in password)
        ):
            return password


class Command(BaseCommand):
    help = 'Akademisyenlere benzersiz geçici şifre atar ve ilk girişte değişikliği zorunlu kılar.'

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--output', help='Yeni şifrelerin yazılacağı CSV dosyası.')
        mode.add_argument('--input', help='Daha önce üretilen şifrelerin okunacağı CSV dosyası.')
        parser.add_argument('--force', action='store_true', help='Var olan çıktı dosyasının üzerine yaz.')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['input']:
            rows = self._read_rows(Path(options['input']))
        else:
            output_path = Path(options['output']).expanduser().resolve()
            if output_path.exists() and not options['force']:
                raise CommandError(f'Çıktı dosyası zaten var: {output_path}')
            academics = list(
                User.objects.filter(profile__user_type='teacher').select_related('profile').order_by('pk')
            )
            if not academics:
                raise CommandError('Geçici şifre atanacak akademisyen bulunamadı.')
            rows = [
                {
                    'email': user.email.strip().lower(),
                    'full_name': user.get_full_name() or user.username,
                    'temporary_password': generate_temporary_password(),
                }
                for user in academics
            ]
            self._write_rows(output_path, rows)

        updated = 0
        for row in rows:
            user = User.objects.select_related('profile').filter(
                email__iexact=row['email'], profile__user_type='teacher'
            ).first()
            if user is None:
                raise CommandError(f"Akademisyen hesabı bulunamadı: {row['email']}")
            user.set_password(row['temporary_password'])
            user.save(update_fields=['password'])
            user.profile.must_change_password = True
            user.profile.save(update_fields=['must_change_password', 'updated_at'])
            updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'{updated} akademisyenin geçici şifresi güncellendi; ilk girişte değişiklik zorunlu.'
        ))

    @staticmethod
    def _read_rows(path):
        if not path.is_file():
            raise CommandError(f'CSV dosyası bulunamadı: {path}')
        with path.open('r', encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.DictReader(handle))
        required = {'email', 'full_name', 'temporary_password'}
        if not rows or not required.issubset(rows[0]):
            raise CommandError('CSV geçici şifre alanlarını içermiyor.')
        return rows

    @staticmethod
    def _write_rows(path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['email', 'full_name', 'temporary_password'])
            writer.writeheader()
            writer.writerows(rows)
